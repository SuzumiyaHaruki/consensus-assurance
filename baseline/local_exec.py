"""One run-scoped STDIO tool; commands execute only in an isolated filesystem."""
import asyncio
import importlib.metadata
import json
import os
import signal
import sys
import sysconfig
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ConfigDict, Field

from consensus_assurance.adapters.runners.experiment import isolated_command
from consensus_assurance.adapters.storage.files import write_json


DESCRIPTION = ('Run an ordinary local test in a private network and PID namespace. The ordinary shell retains its current restrictions. '
               'Use this tool for TCP or a bounded isolated run; start all communicating processes within the same invocation. '
               'Returns execution output, not an audit verdict. cwd is relative to this run working copy. '
               'No background service survives an invocation. Complete raw logs are retained read-only.')


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    argv: list[str] = Field(min_length=1)
    cwd: str = '.'
    timeout_seconds: float | None = Field(default=None, gt=0)


def tool():
    return types.Tool(name='isolated_exec', description=DESCRIPTION, inputSchema=Arguments.model_json_schema())


def server_settings(control, action_timeout):
    script = Path(__file__).resolve()
    # -S excludes site hooks/.pth; only explicitly selected installed packages and trusted source load.
    code = 'import sys,runpy;sys.path[:0]=' + repr([str(script.parents[1]/'src'), sysconfig.get_path('purelib')])
    code += ';runpy.run_path(' + repr(str(script)) + ',run_name="__main__")'
    return {'command': '/usr/bin/env', 'args': ['-i', 'PATH=/usr/bin:/bin', 'LANG=C.UTF-8',
            sys.executable, '-I', '-S', '-c', code, str(control)], 'cwd': str(script.parent),
            'env_vars': [], 'enabled_tools': ['isolated_exec'], 'required': True,
            'startup_timeout_sec': 15, 'tool_timeout_sec': action_timeout + 5,
            'default_tools_approval_mode': 'approve'}


def identity(settings, control):
    return {'server': settings, 'tool': tool().model_dump(mode='json', exclude_none=True),
            'protocol_package': {'name': 'mcp', 'version': importlib.metadata.version('mcp')},
            'permissions': {key: control[key] for key in ('work','records','tool_roots','read_only_roots','environment','action_timeout')},
            'isolation': 'allowlisted files; private network/PID/IPC; clean environment; serial calls'}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def remaining(control, requested):
    limits = {'requested': requested if requested is not None else control['action_timeout'],
              'action_timeout': control['action_timeout'],
              'agent_turn_timeout': control['turn_deadline'] - time.monotonic(),
              'total_seconds': control['run_deadline'] - time.monotonic()}
    key = min(limits, key=limits.get)
    return max(0, limits[key]), key


def validate_directory(work, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('cwd must remain relative to this run working copy')
    resolved = (work/path).resolve(strict=True)
    if not resolved.is_relative_to(work) or not resolved.is_dir():
        raise ValueError('cwd escapes this run working copy or is not a directory')
    return resolved


async def execute(control, arguments, request_id):
    args = Arguments.model_validate(arguments)
    if not args.argv[0] or any('\0' in value for value in args.argv):
        raise ValueError('argv needs a nonempty executable and must not contain NUL')
    if not control['allow_experiments']:
        raise ValueError('Local execution is not authorized')
    work = Path(control['work'])
    cwd = validate_directory(work, args.cwd)
    execution_id = uuid4().hex
    folder = Path(control['records'])/execution_id
    folder.mkdir(parents=True)
    limit, basis = remaining(control, args.timeout_seconds)
    record = {'execution_id': execution_id, 'turn': control['turn'], 'mcp_request_id': request_id,
              'argv': args.argv, 'cwd': str(cwd), 'requested_timeout_seconds': args.timeout_seconds,
              'timeout_seconds': limit, 'timeout_limit': basis, 'started_at': timestamp(),
              'status': 'running', 'exit_code': None, 'service_pid': os.getpid()}
    started = time.monotonic()
    write_json(folder/'result.json', record)
    child = None
    pumps = []
    try:
        if limit <= 0:
            record['status'] = 'timeout'
        else:
            command = isolated_command(args.argv, work, cwd, control['tool_roots'], control['read_only_roots'])
            record['command'] = command
            write_json(folder/'result.json', record)
            async def capture(stream, path):
                with path.open('wb') as output:
                    while data := await stream.read(65536):
                        output.write(data); output.flush()
            if started + limit <= time.monotonic():
                record['status'] = 'timeout'
            else:
                child = await asyncio.create_subprocess_exec(*command, cwd='/', env=control['environment'],
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, start_new_session=True)
                pumps = [asyncio.create_task(capture(stream, folder/(name+'.txt')))
                         for name, stream in (('stdout', child.stdout), ('stderr', child.stderr))]
                record['process_id'] = child.pid
                write_json(folder/'result.json', record)
                try:
                    await asyncio.wait_for(child.wait(), max(0, started + limit - time.monotonic()))
                    record.update(status='completed', exit_code=child.returncode)
                except asyncio.TimeoutError:
                    record['status'] = 'timeout'
    except asyncio.CancelledError:
        record.update(status='cancelled', reason=control.get('cancellation_reason', 'request_cancelled'))
        raise
    except OSError as exc:
        record.update(status='launch_error', reason=str(exc))
    finally:
        with anyio.CancelScope(shield=True):
            if child:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                await asyncio.wait_for(child.wait(), 3)
                record['exit_code'] = child.returncode
                await asyncio.wait_for(asyncio.gather(*pumps), 3)
            record.update(ended_at=timestamp(), elapsed_seconds=time.monotonic()-started)
            for name in ('stdout', 'stderr'):
                path = folder/(name+'.txt'); path.touch(exist_ok=True)
                with path.open('rb') as stream: preview = stream.read(8192)
                record[name] = {'path': str(path), 'preview': preview.decode(errors='replace'),
                                'truncated': path.stat().st_size > len(preview), 'bytes': path.stat().st_size}
            if record['status'] == 'completed' and record['exit_code'] and record['stderr']['preview'].startswith('bwrap:'):
                record['status'] = 'launch_error'
            write_json(folder/'result.json', record)
    return record


async def serve(path, parent_fd):
    control = json.loads(path.read_text())
    server = Server('baseline_local')
    lock = anyio.Lock()
    @server.list_tools()
    async def list_tools():
        return [tool()]
    @server.call_tool()
    async def call_tool(name, arguments):
        if name != 'isolated_exec':raise ValueError('Unknown tool')
        async with lock:
            return await execute(control, arguments, server.request_context.request_id)
    # STDIO EOF and termination cancel in-flight work rather than waiting for its requested time.
    with anyio.CancelScope() as scope:
        loop = asyncio.get_running_loop()
        def stop(reason):
            control.setdefault('cancellation_reason', reason)
            scope.cancel()
        for sig in (signal.SIGTERM, signal.SIGINT):loop.add_signal_handler(sig, stop, sig.name)
        # A pidfd tracks the parent process, not the transient thread that spawned us.
        loop.add_reader(parent_fd, stop, 'parent_exit')
        reader = asyncio.StreamReader(limit=sys.maxsize)
        transport = None
        class Input:
            def __aiter__(self):return self
            async def __anext__(self):
                line = await reader.readline()
                if not line:
                    stop('stdio_eof')
                    raise StopAsyncIteration
                return line.decode('utf-8')
        try:
            transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
            async with stdio_server(stdin=Input()) as streams:
                await server.run(*streams, server.create_initialization_options())
        finally:
            loop.remove_reader(parent_fd)
            if transport:transport.close()


def reconcile(records, turn, reason):
    """Preserve abruptly interrupted executions without inventing completion receipts."""
    for path in Path(records).glob('*/result.json'):
        record = json.loads(path.read_text())
        if record['turn'] == turn and record['status'] == 'running':
            record.update(status='interrupted', reason=reason, observed_at=timestamp())
            write_json(path, record)


@asynccontextmanager
async def app_server(command, cwd, environment, folder, timeout):
    """Bounded local Codex protocol session with raw responses retained."""
    folder.mkdir(parents=True, exist_ok=True)
    child = None
    with (folder/'stderr.log').open('wb') as err, (folder/'stdout.jsonl').open('wb') as out:
        try:
            child = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=err, start_new_session=True)
            number = 0
            async def request(method, params):
                nonlocal number
                number += 1
                child.stdin.write((json.dumps({'id':number, 'method':method, 'params':params})+'\n').encode())
                await child.stdin.drain()
                while True:
                    line = await child.stdout.readline()
                    if not line:raise ValueError('Codex app server ended before a response')
                    out.write(line); out.flush()
                    response = json.loads(line)
                    if response.get('id') == number:
                        if 'error' in response:raise ValueError(str(response['error']))
                        return response['result']
            with anyio.fail_after(timeout):
                await request('initialize', {'clientInfo': {'name':'baseline-local-probe', 'version':'1'},
                    'capabilities': {'experimentalApi': True}})
                yield request
        finally:
            if child:
                try:os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                await asyncio.wait_for(child.communicate(), 3)


if __name__ == '__main__':
    parent = os.getppid()
    parent_fd = os.pidfd_open(parent)
    try:
        if os.getppid() != parent:sys.exit(1)
        anyio.run(serve, Path(sys.argv[1]), parent_fd)
    finally:
        os.close(parent_fd)
