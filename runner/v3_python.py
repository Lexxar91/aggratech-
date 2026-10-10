"""Python 3.14: прокси опубликованных адаптеров вместо проверяющего кода в задаче."""

import asyncio
import json
from time import perf_counter
from uuid import uuid4

from pydantic import JsonValue

from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionStatus,
    RunnerUnavailable,
    V3ExecutionRequest,
    V3ExecutionResult,
)
from runner.sandbox import OutputLimit, SandboxPolicy, create_command, docker_control
from runner.v3_adapters import (
    AdapterSession,
    integer_value,
    list_value,
    object_value,
    string_value,
)

# В контейнере только ответ и RPC-прокси предоставленных интерфейсов.
# Здесь нет эталонов, рубрик, сравнения результатов или будущих сценариев.
V3_WRAPPER = r"""
import concurrent.futures, copy, hmac, json, queue, sys, threading
wire_in, wire_out = sys.stdin, sys.stdout
initial = json.loads(wire_in.readline())
source = initial['source']
pending, counter, case = {}, 0, 0
send_lock, pending_lock = threading.Lock(), threading.Lock()
commands = queue.Queue()
actor = threading.local()

def send(value):
    raw = json.dumps(value, allow_nan=False, separators=(',', ':'))
    with send_lock:
        wire_out.write(raw + '\n')
        wire_out.flush()

def reader():
    for line in wire_in:
        value = json.loads(line)
        if 'run' in value:
            commands.put(value)
        else:
            with pending_lock:
                channel = pending.get(value['id'])
            if channel is None:
                sys.exit(10)
            channel.put(value['reply'])
    commands.put(None)

def encode(value):
    if isinstance(value, bytes):
        return {'$bytes': value.hex()}
    if isinstance(value, GeneratedRows):
        return {'$generated_consumed': value.consumed}
    if isinstance(value, (Proxy, Stream)):
        return {'$adapter' if isinstance(value, Proxy) else '$stream': value.target}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    return value

def decode(value):
    if isinstance(value, dict):
        if '$bytes' in value:
            return bytes.fromhex(value['$bytes'])
        if '$adapter' in value:
            return Proxy(value['$adapter'])
        if '$stream' in value:
            return Stream(value['$stream'])
        if '$generated' in value:
            return GeneratedRows(value['$generated'])
        if '$tuple' in value:
            return tuple(decode(v) for v in value['$tuple'])
        if '$frozenset' in value:
            return frozenset(decode(v) for v in value['$frozenset'])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value

def rpc(target, method, args):
    global counter
    channel = queue.Queue()
    with pending_lock:
        counter += 1
        ident = counter
        pending[ident] = channel
    send({'id': ident, 'case': case, 'actor': getattr(actor, 'index', 0),
          'target': target, 'method': method, 'args': encode(args)})
    result = channel.get()
    with pending_lock:
        pending.pop(ident)
    if isinstance(result, dict) and '$exception' in result:
        errors = {'StopIteration': StopIteration, 'TimeoutError': TimeoutError,
                  'OSError': OSError, 'ValueError': ValueError,
                  'RuntimeError': RuntimeError}
        raise errors.get(result['$exception'], ValueError)()
    return decode(result)

class Proxy:
    def __init__(self, target): self.target = target
    def __call__(self, *args): return rpc(self.target, 'call', args)
    def __getattr__(self, method):
        if method.startswith('_'): raise AttributeError(method)
        return lambda *args: rpc(self.target, method, args)

class Stream:
    def __init__(self, target): self.target = target
    def __iter__(self):
        rpc('stream:' + self.target, 'iter', [])
        return self
    def __next__(self): return rpc('stream:' + self.target, 'next', [])

class GeneratedRows:
    def __init__(self, spec):
        self.spec, self.consumed = spec, 0
    def __iter__(self): return self
    def __next__(self):
        if self.consumed >= self.spec['count']: raise StopIteration
        index = self.consumed
        self.consumed += 1
        row = self.spec['row'].copy()
        row['amount'] = index % 7
        if 'record_id' in row:
            row['record_id'] = index % 20
            row['revision'] = index
            row['revision_id'] = index
        return row

hmac.compare_digest = lambda a, b: rpc('digest', 'compare', [a, b])
threading.Thread(target=reader, daemon=True).start()

while (command := commands.get()) is not None:
    case = command['case']
    namespace = {'__name__': '__candidate__'}
    spec = command['run']
    try:
        exec(compile(source, 'solution.py', 'exec'), namespace)
        invocations = spec['invocations']
        barrier = threading.Barrier(len(invocations)) if spec.get('parallel') else None
        def invoke(pair):
            index, invocation = pair
            actor.index = index
            args = decode(invocation.get('args', []))
            kwargs = decode(invocation.get('kwargs', {}))
            if invocation.get('restart'):
                namespace.clear()
                namespace['__name__'] = '__candidate__'
                exec(compile(source, 'solution.py', 'exec'), namespace)
            try:
                if barrier is not None: barrier.wait()
                result = namespace[invocation['function']](*args, **kwargs)
                return {'value': encode(result), 'input_after': encode(args)}
            except Exception as error:
                return {'error': type(error).__name__, 'input_after': encode(args)}
        if barrier is not None:
            executor = concurrent.futures.ThreadPoolExecutor
            with executor(max_workers=len(invocations)) as pool:
                results = list(pool.map(invoke, enumerate(invocations)))
        else:
            results = [invoke(pair) for pair in enumerate(invocations)]
        send({'case': case, 'result': results})
    except Exception as error:
        send({'case': case, 'result': [{'error': type(error).__name__}]})
"""

PYTHON_TASKS = {
    f"{stem}-{level}"
    for stem in ("X1-PY", "X2", "X4", "X6", "Y1-PY", "Y2", "Y4", "Y6")
    for level in ("J", "M")
}


async def execute_python_v3(request: V3ExecutionRequest) -> V3ExecutionResult:
    """Сравнение с ожиданиями остаётся в worker; runner возвращает наблюдения."""
    if request.language != "python" or request.task_id not in PYTHON_TASKS:
        raise ValueError("python_task_not_allowed")
    if len(request.model_dump_json().encode()) > 131072:
        raise ValueError("input_too_large")
    name = f"aggratech-task-{uuid4().hex}"
    started = perf_counter()
    outputs: list[JsonValue] = []
    status: ExecutionStatus = "completed"
    created = False
    process: asyncio.subprocess.Process | None = None
    try:
        command = create_command(name, SandboxPolicy())
        command[-1] = V3_WRAPPER
        code, _ = await docker_control(*command[1:])
        if code:
            raise RunnerUnavailable("python_container_creation_failed")
        created = True
        process = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            "--interactive",
            name,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536,
        )
        assert process.stdin and process.stdout and process.stderr
        written, read = 0, 0

        async def send(value: dict[str, JsonValue]) -> None:
            nonlocal written
            assert process and process.stdin
            data = (
                json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"
            ).encode()
            written += len(data)
            if written > 262144:
                raise OutputLimit
            process.stdin.write(data)
            await process.stdin.drain()

        async def errors() -> None:
            nonlocal read
            assert process and process.stderr
            while data := await process.stderr.read(4096):
                read += len(data)
                if read > 65536:
                    raise OutputLimit

        async def scenarios() -> None:
            nonlocal read
            assert process and process.stdout and process.stdin
            await send({"source": request.source})
            for index, scenario in enumerate(request.scenarios):
                session = AdapterSession(scenario)
                invocations = list_value(scenario.get("invocations", []))
                if not 1 <= len(invocations) <= 8:
                    raise ValueError("invalid_python_invocations")
                await send(
                    {
                        "case": index,
                        "run": {
                            "invocations": invocations,
                            "parallel": scenario.get("parallel", False),
                        },
                    }
                )
                pending_replies: list[tuple[int, JsonValue]] = []
                async with asyncio.timeout(5):
                    while line := await process.stdout.readline():
                        read += len(line)
                        if read > 65536:
                            raise OutputLimit
                        value = object_value(json.loads(line))
                        if value.get("case") != index:
                            raise ValueError("python_protocol_case_mismatch")
                        if "result" in value:
                            results = list_value(value["result"])
                            outputs.append(
                                {
                                    "status": "completed",
                                    "results": results,
                                    "return_values": [
                                        object_value(item).get("value")
                                        for item in results
                                    ],
                                    "observed": session.observation(),
                                }
                            )
                            break
                        ident = integer_value(value["id"])
                        target, method = (
                            string_value(value["target"]),
                            string_value(value["method"]),
                        )
                        try:
                            reply = session.dispatch(
                                target, method, list_value(value["args"])
                            )
                        except KeyError, IndexError, TypeError:
                            reply = {"$exception": "ValueError"}
                        if scenario.get("barrier") == f"{target}.{method}":
                            pending_replies.append((ident, reply))
                            if len(pending_replies) < len(invocations):
                                continue
                            for pending_id, pending_reply in pending_replies:
                                await send({"id": pending_id, "reply": pending_reply})
                            pending_replies.clear()
                        else:
                            await send({"id": ident, "reply": reply})
                    else:
                        raise ValueError("python_protocol_incomplete")
            process.stdin.close()
            await process.wait()

        async with asyncio.timeout(45):
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(errors())
                    group.create_task(scenarios())
            except* OutputLimit:
                status = "output_limit"
            except* TimeoutError:
                status = "timeout"
            except* ValueError, UnicodeError, BrokenPipeError, ConnectionResetError:
                status = "candidate_error"
        if status == "completed" and process.returncode:
            status = "runtime_error"
    except TimeoutError:
        status = "timeout"
    finally:
        if created:
            code, _ = await docker_control("rm", "--force", name)
            if code:
                raise RunnerUnavailable("python_container_cleanup_failed")
        if process is not None:
            if process.returncode is None:
                process.kill()
            assert process.stdout and process.stderr

            async def discard(stream: asyncio.StreamReader) -> None:
                while await stream.read(4096):
                    pass

            async with asyncio.timeout(3):
                async with asyncio.TaskGroup() as group:
                    group.create_task(discard(process.stdout))
                    group.create_task(discard(process.stderr))
                    group.create_task(process.wait())
    return V3ExecutionResult(
        status=status,
        outputs=outputs,
        runtime_image=PYTHON_IMAGE,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
