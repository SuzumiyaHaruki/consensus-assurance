import pytest
from consensus_assurance.core.types import Material, SourceAnchor
from consensus_assurance.workflow.locations import locate


def material(text,start=1,file='sample.go'):
    return Material(id=f'{file}:{start}:{start+len(text.splitlines())-1}',file=file,start_line=start,end_line=start+len(text.splitlines())-1,kind='code_observation',text=text,content_digest='synthetic-source')


def binding(m,symbol='accept',start=2,end=2,anchor=None):
    return SourceAnchor(material_id=m.id, symbol=symbol, start_line=start, end_line=end, anchor=anchor)


def test_declaration_outside_read_material_requires_reading():
    partial=material('  value++\n}\n',2);b=binding(partial)
    assert locate(b,{partial.id:partial})[0] is None
    complete=material('func accept() {\n  value++\n}\n')
    assert locate(b,{partial.id:partial,complete.id:complete})[0]['material_id']==complete.id
    prefix=material('func accept() {\n  value++\n')
    assert not locate(binding(prefix),{prefix.id:prefix})[0]['boundary_complete']


def test_java_declarations_resolve_actual_owner_and_overload_range():
    from consensus_assurance.workflow.locations import declarations
    m=material('''class First {
    @Deprecated public int take(int n) {
        return n;
    }
    public int take() { return 0; }
    static class Nested { void act() {} }
}
interface Second { int take(); }
// class Invented { void ignored() {} }
''', file='Sample.java')
    assert locate(binding(m,'First.take',3,3),{m.id:m})[0]['start_line']==2
    assert locate(binding(m,'First.take',5,5),{m.id:m})[0]['start_line']==5
    assert locate(binding(m,'Second.take',3,3),{m.id:m})[0] is None
    assert any(d['owner']=='First.Nested' and d['symbol']=='act' for d in declarations(m))
    assert not any(d['symbol']=='ignored' for d in declarations(m))
    partial=material('    public int take(int n) {\n        return n;\n',2,file='Sample.java')
    assert locate(binding(partial,'First.take',3,3),{partial.id:partial})[0] is None


def test_qualified_interface_member_requires_actual_owner_and_anchor():
    from consensus_assurance.workflow.locations import location_context
    m=material('type First interface {\n Response() int\n}\ntype Second interface {\n Response() int\n}\n')
    b=binding(m,'First.Response',2,2)
    anchor,error=locate(b,{m.id:m})
    assert not error and anchor['symbol']=='First.Response' and anchor['boundary_complete']
    assert [d['start'] for d in location_context(b,{m.id:m})['candidates']]==[2]
    assert locate(binding(m,'Second.Response',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'Unknown.Response',2,2),{m.id:m})[0] is None
    b.anchor={**anchor,'start_line':1}
    assert locate(b,{m.id:m})[0] is None


def test_member_without_acquired_owner_is_not_resolved_by_suffix():
    m=material(' Response() int\n}\n',2)
    assert locate(binding(m,'First.Response',2,2),{m.id:m})[0] is None


@pytest.mark.parametrize('receiver',['r *First','r First','r *First[T]','*First'])
def test_receiver_qualified_method_uses_declared_type(receiver):
    from consensus_assurance.workflow.locations import location_context
    m=material('func ('+receiver+') accept() {\n value++\n}\nfunc (s *Second) accept() {\n value--\n}\n')
    b=binding(m,'First.accept',2,2)
    anchor,error=locate(b,{m.id:m})
    assert not error and anchor['start_line']==1 and anchor['symbol']=='First.accept'
    assert [d['start'] for d in location_context(b,{m.id:m})['candidates']]==[1]
    assert locate(binding(m,'Second.accept',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'r.accept',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'First.accept',5,5),{m.id:m})[0] is None


def test_local_closure_does_not_inherit_surrounding_receiver():
    m=material('func (r *First) accept() {\n work := func() {\n  value++\n }\n}\n')
    assert locate(binding(m,'First.work',3,3),{m.id:m})[0] is None
    assert locate(binding(m,'work',3,3),{m.id:m})[0] is not None


def test_anchor_correction_does_not_fix_cross_declaration_behavior():
    from consensus_assurance.workflow.locations import location_context
    from consensus_assurance.workflow.locations import location_evidence
    m=material('func save() {\n value++\n}\nfunc discard() {\n value--\n}\n')
    b=binding(m,'save',2,5)
    assert not location_context(b,{m.id:m})['candidates'][0]['contains_behavior']
    b.anchor={'material_id':m.id,'symbol':'save','start_line':1,'end_line':1}
    evidence,error=location_evidence(b,{m.id:m})
    assert evidence is None and error


def test_rust_declarations_use_syntax_and_acquired_impl_owner():
    from consensus_assurance.workflow.locations import declarations
    m=material('''const TEXT: &str = r#"fn invented() {}"#;
/* fn commented() { /* nested */ } */
impl<T> First<T> {
    pub fn take<'a>(&self, value: &'a str) -> &'a str {
        value
    }
}
impl Second {
    pub fn take(&self) {}
}
''',file='sample.rs')
    assert not {'invented','commented'} & {d['symbol'] for d in declarations(m)}
    anchor,error=locate(binding(m,'First::take',5,5),{m.id:m})
    assert not error and anchor['start_line']==4 and anchor['boundary_complete']
    assert locate(binding(m,'Second::take',5,5),{m.id:m})[0] is None
    assert locate(binding(m,'First::take',5,9),{m.id:m})[0] is None
    fragment=material('pub fn take(&self) {}\n',9,file='sample.rs')
    assert locate(binding(fragment,'Second::take',9,9),{fragment.id:fragment})[0] is None
    assert locate(binding(fragment,'take',9,9),{fragment.id:fragment})[0]
    incomplete=material('pub fn take(value:i64) {\n value+1\n',file='sample.rs')
    assert locate(binding(incomplete,'take',2,2),{incomplete.id:incomplete})[0] is None


@pytest.mark.parametrize('responsibility,anchored,missing',[
    ('',True,['responsibility']),
    ('The acquired function handles the required input.',False,['anchors']),
    (' ',False,['responsibility','anchors'])])
def test_requirement_diagnostic_identifies_only_missing_fields(responsibility,anchored,missing):
    from types import SimpleNamespace
    from consensus_assurance.core.types import ExperimentBasis
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.experiments import validate_basis
    m=material('func accept() {\n value++\n}\n')
    basis=ExperimentBasis(harness={'kind':'test','source':'fixture'},source_ids=[m.id],
        scope={'description':'One local call'},prefix='Use the acquired local function.',
        requirement='The operation increments the input.',responsibility=responsibility,
        anchors=[binding(m)] if anchored else [])
    with pytest.raises(DiagnosticError) as rejected:
        validate_basis(SimpleNamespace(materials=[m],knowledge=[]),basis,SimpleNamespace(harness_kind='test'))
    diagnostic,=rejected.value.diagnostics
    assert diagnostic.paths==['/experiment/'+name for name in missing]
    assert diagnostic.details['missing_fields']==missing


@pytest.mark.parametrize('return_type',['interface{}','struct{ Value int }'])
def test_go_accessor_return_type_braces_do_not_hide_actual_body(return_type):
    source='func (x *Result) Response() '+return_type+' {\n    return x.response\n}\n'
    m=material(source, file='future.go')
    anchor,error=locate(binding(m,'Response',1,3),{m.id:m})
    assert anchor and anchor['start_line']==1,error


def test_go_named_slice_groups_only_contiguous_matching_receiver_methods():
    from consensus_assurance.workflow.locations import declarations
    text='type Scores []int\n\nfunc (s Scores) Len() int { return len(s) }\nfunc other() {}\nfunc (s Scores) Less(i, j int) bool { return s[i] < s[j] }'
    m=material(text,file='sort.go')
    d=next(d for d in declarations(m) if d['symbol']=='Scores' and d['kind']=='declaration')
    assert d['start']==1 and d['end']==3


def test_contiguous_prefix_can_prove_owner_without_claiming_complete_end():
    text='func (x *State) Handle(\n v int,\n) {\n f := func() { println("}") }\n f()\n'
    def source(id,a,z,version='same'):
        return Material(id=id,file='state.go',start_line=a,end_line=z,text='\n'.join(text.splitlines()[a-1:z]),content_digest=version,kind='code_observation')
    b=SourceAnchor(material_id='body', symbol='Handle', start_line=5, end_line=5, anchor={'material_id':'head','symbol':'Handle','start_line':1,'end_line':3,'kind':'declaration'})
    assert locate(b,{'head':source('head',1,3),'body':source('body',4,5)})[0]
    assert not locate(b,{'head':source('head',1,3),'body':source('body',5,5)})[0]
    assert not locate(b,{'head':source('head',1,3),'body':source('body',4,5,'different')})[0]


@pytest.mark.parametrize('cuts', [[(1,8)],[(1,2),(3,5),(6,8)],[(1,5),(4,8)]])
def test_multiline_signature_and_receiver_identity_survive_read_partition(cuts):
    text='func (x *A) Handle(\n  v int,\n) {\n println(v)\n}\nfunc (x *B) Handle() {\n println(2)\n}'
    materials={str(i):Material(id=str(i),file='state.go',start_line=a,end_line=z,text='\n'.join(text.splitlines()[a-1:z]),content_digest='version',kind='code_observation') for i,(a,z) in enumerate(cuts)}
    body=next(m for m in materials.values() if m.start_line<=4<=m.end_line)
    head=next(m for m in materials.values() if m.start_line==1)
    b=SourceAnchor(material_id=body.id, symbol='Handle', start_line=4, end_line=4, anchor={'material_id':head.id,'symbol':'Handle','start_line':1,'end_line':3,'kind':'declaration'})
    anchor,error=locate(b,materials);assert anchor,error
    assert anchor['start_line']==1 and anchor['boundary_complete']
    b.anchor.start_line=6;b.anchor.end_line=6
    assert not locate(b,materials)[0]


def test_comment_name_does_not_create_identity_and_interface_is_distinct():
    m=Material(id='code',file='state.go',start_line=1,end_line=5,content_digest='v',kind='code_observation',text='// func Fake() {\ntype Store interface {\n Save(\n  value int) error\n}')
    b=SourceAnchor(material_id=m.id, symbol='Fake', start_line=1, end_line=1)
    assert not locate(b,{m.id:m})[0]
    b.symbol='Store';b.start_line=2;b.end_line=5
    assert locate(b,{m.id:m})[0]


def test_prefix_ending_inside_raw_string_cannot_fabricate_function_end():
    from consensus_assurance.workflow.locations import declarations
    m=Material(id='prefix',file='state.go',start_line=1,end_line=4,kind='code_observation',content_digest='v',text='func Handle() {\n value := `raw\n } fake boundary\n still inside literal')
    definition=next(d for d in declarations(m) if d['symbol']=='Handle' and d['kind']=='declaration')
    assert definition['end'] is None and not definition['closed']
