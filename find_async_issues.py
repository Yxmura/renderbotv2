import re
import os

def find_unawaited_coroutines(directory):
    """Find all unawaited coroutine calls in Python files."""
    pattern = r'(?<!await\s)(?<!async\s)(?<!\.\s)(\b\w+\s*\([^)]*\))'
    coroutine_pattern = r'async\s+def\s+(\w+)'
    
    coroutine_names = set()
    issues = []
    
    # First pass: Find all coroutine function names
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    for match in re.finditer(coroutine_pattern, content):
                        coroutine_names.add(match.group(1))
    
    # Second pass: Find unawaited coroutine calls
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                with open(path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f, 1):
                        for match in re.finditer(pattern, line):
                            func_call = match.group(1).split('(')[0].strip()
                            if func_call in coroutine_names and not line.lstrip().startswith('def ') and not line.lstrip().startswith('#'):
                                issues.append((path, i, line.strip(), func_call))
    
    return issues

if __name__ == "__main__":
    directory = os.path.dirname(os.path.abspath(__file__))
    issues = find_unawaited_coroutines(directory)
    
    if issues:
        print("Found potential unawaited coroutines:")
        for issue in issues:
            print(f"File: {issue[0]}")
            print(f"Line {issue[1]}: {issue[2]}")
            print(f"Coroutine: {issue[3]}")
            print("-" * 80)
    else:
        print("No unawaited coroutines found.")
