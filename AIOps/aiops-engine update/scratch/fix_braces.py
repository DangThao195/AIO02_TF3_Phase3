file_path = "llm_diagnostician.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Normalize line endings
content = content.replace("\r\n", "\n")

# Target replacement 1
target_start = "Trả về kết quả ở định dạng JSON duy nhất như sau:\n{"
replacement_start = "Trả về kết quả ở định dạng JSON duy nhất như sau:\n{{"

# Target replacement 2
target_end = "}\n\"\"\""
replacement_end = "}}\n\"\"\""

if target_start in content:
    content = content.replace(target_start, replacement_start)
    print("Found and replaced target_start!")
else:
    print("WARNING: target_start not found!")

if target_end in content:
    content = content.replace(target_end, replacement_end)
    print("Found and replaced target_end!")
else:
    print("WARNING: target_end not found!")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Finished processing.")
