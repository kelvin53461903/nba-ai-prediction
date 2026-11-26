"""Inspect the MIT-licensed SBR archive schema and 2020-22 coverage; no DB writes."""
import json,sys,urllib.request,collections
URL="https://raw.githubusercontent.com/flancast90/sportsbookreview-scraper/main/data/nba_archive_10Y.json"
def main():
 req=urllib.request.Request(URL,headers={"User-Agent":"NBA-AI-V8.0-SBR-Archive-Audit/1.0"})
 with urllib.request.urlopen(req,timeout=90) as r: payload=r.read()
 obj=json.loads(payload)
 print("ROOT_TYPE:",type(obj).__name__,"BYTES:",len(payload))
 if isinstance(obj,dict):
  print("ROOT_KEYS:",list(obj.keys())[:50])
  records=None
  for k,v in obj.items():
   if isinstance(v,list): records=v; print("RECORD_LIST_KEY:",k,"COUNT:",len(v)); break
 elif isinstance(obj,list): records=obj
 else: raise RuntimeError("Unexpected archive root type")
 if records is None or not records: raise RuntimeError("No records list found")
 print("SAMPLE_RECORD:",json.dumps(records[0],ensure_ascii=False)[:6000])
 counts=collections.Counter()
 for row in records:
  if not isinstance(row,dict): continue
  text=json.dumps(row).lower()
  if "2020" in text: counts["contains_2020"]+=1
  if "2021" in text: counts["contains_2021"]+=1
  if "2022" in text: counts["contains_2022"]+=1
 print("YEAR_TEXT_COUNTS:",dict(counts))
 print("PASS: archive fetched for schema inspection only; no database writes")
if __name__=="__main__":
 try: main()
 except Exception as e:
  print(f"SBR ARCHIVE AUDIT FAILED: {type(e).__name__}: {e}",file=sys.stderr); sys.exit(1)
