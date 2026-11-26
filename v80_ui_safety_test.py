"""Static UI safety checks for the V8.0 Streamlit app."""
import ast, re, sys
from pathlib import Path

APP=Path("app.py")
def main():
 if not APP.is_file(): raise RuntimeError("app.py missing")
 source=APP.read_text(encoding="utf-8")
 ast.parse(source)
 ui_lines=[]
 for number,line in enumerate(source.splitlines(),1):
  if re.search(r"st\.(?:write|metric|caption|markdown|info|success|warning|error)\s*\(",line):
   if re.search(r"10\s*,\s*000|10000\s*(?:次|次模擬| simulations| results)",line,re.I):
    ui_lines.append(number)
 if ui_lines: raise RuntimeError(f"10,000 simulation output appears in UI at lines {ui_lines}")
 if "Raw simulation counts, intervals and histograms are intentionally hidden from the website." not in source:
  raise RuntimeError("Required UI privacy/display guard comment missing")
 if "V8.0 校準測試版" not in source or "未證明優於市場基準" not in source:
  raise RuntimeError("V8.0 market-risk disclosure missing")
 print("PASS: app.py syntax")
 print("PASS: raw 10,000-run simulation counts/results are not exposed in UI")
 print("PASS: V8.0 market-risk disclosure is present")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"V8.0 UI SAFETY TEST FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
