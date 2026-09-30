import inspect, contextlib, sys

# Test 1: Does @asynccontextmanager work correctly?
@contextlib.asynccontextmanager
async def test_lifespan(app):
    print('setup')
    yield
    print('teardown')

lc = test_lifespan
print(f"type: {type(lc)}")
print(f"iscoroutinefunction: {inspect.iscoroutinefunction(lc)}")
print(f"isasyncgenfunction: {inspect.isasyncgenfunction(lc)}")
print(f"isasyncgen: {inspect.isasyncgen(lc)}")
print(f"callable: {callable(lc)}")

# Test 2: Check our actual lifespan
sys.path.insert(0, 'src')
import agent_runtime.server.app as app_module
actual_lc = app_module.app.router.lifespan_context
print()
print(f"=== Our actual lifespan ===")
print(f"type: {type(actual_lc)}")
print(f"iscoroutinefunction: {inspect.iscoroutinefunction(actual_lc)}")
print(f"isasyncgenfunction: {inspect.isasyncgenfunction(actual_lc)}")
print(f"isasyncgen: {inspect.isasyncgen(actual_lc)}")
print(f"callable: {callable(actual_lc)}")

# Test 3: Check if it's a FastAPI-wrapped lifespan
print()
print(f"=== FastAPI lifespan wrapping ===")
print(f"Router lifespan attr: {type(app_module.app.router).__name__}")
if hasattr(app_module.app.router, 'lifespan_context'):
    print(f"Router.lifespan_context: {app_module.app.router.lifespan_context}")
if hasattr(app_module.app.router, 'on_startup'):
    print(f"Router.on_startup: {app_module.app.router.on_startup}")
if hasattr(app_module.app.router, 'on_shutdown'):
    print(f"Router.on_shutdown: {app_module.app.router.on_shutdown}")