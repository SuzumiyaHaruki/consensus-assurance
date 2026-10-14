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
    original={'bindings':[b.model_dump(mode='json')]}
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
