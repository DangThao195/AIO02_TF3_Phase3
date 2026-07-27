from src.tools.registry import ToolRegistry
specs = ToolRegistry.get_all_specs()
print('Registered tools:', len(specs))
for name in sorted(specs.keys()):
    spec = specs[name]
    print('  {}: write={}, input_keys={}'.format(name, spec.is_write, list(spec.input_schema.get("properties", {}).keys())))