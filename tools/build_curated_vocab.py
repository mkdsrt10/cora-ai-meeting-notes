import sys, json, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import credentials, db, paths  # noqa: E401,E402

client = credentials.get_client()

recs = db.get_all_recordings()
meetings_context = []
for r in recs[:30]:
    rid = r['id']
    title = r.get('title') or ''
    call_sum = db.get_recording_data(rid, 'call_summary') or {}
    meta = db.get_recording_data(rid, 'metadata') or {}
    overview = call_sum.get('overview') or meta.get('recording_name') or ''
    decisions = call_sum.get('decisions') or []
    keywords = call_sum.get('keywords') or []
    if overview or decisions or keywords:
        meetings_context.append({
            'title': title or meta.get('recording_name') or rid,
            'overview': overview[:300],
            'keywords': keywords,
            'decisions': decisions[:3],
        })

prompt = f"""
You are a principal speech-to-text systems engineer. We use Whisper on Apple Silicon to transcribe enterprise engineering and leadership meetings (English + Hindi/Hinglish code-mixing).

Below is context from our recent meetings (titles, overviews, keywords, decisions):
{json.dumps(meetings_context, indent=2)}

TASK:
Extract a clean, high-signal, domain-specific vocabulary list for Whisper's initial_prompt.
Rules:
1. EXCLUDE all conversational pronouns, contractions, numbers, and common English stopwords (e.g. NEVER include 'I\\'m', 'I\\'ll', 'Yes', 'It\\'s', 'That\\'s', 'Participant', '29:35', 'None', 'None noted').
2. Include ONLY genuine proper nouns, human names, client organizations, internal product names, database/tech concepts, and common spoken Hinglish tokens.
3. Standardize phonetic Hinglish spellings (e.g. 'karega', 'matlab', 'bhej dungi', 'kar dunga', 'dekh leta', 'baat karni').

Output strictly valid JSON with keys:
- 'people': list of real human names
- 'clients_and_orgs': list of company / client names
- 'products_and_projects': list of project / product names
- 'technical_terms': list of technical terms / acronyms / database concepts
- 'hinglish_phrases': list of frequent phonetic Hindi/Hinglish words

Output ONLY raw JSON.
"""

res = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt,
)

raw = res.text.strip()
raw = re.sub(r"^```json\s*", "", raw)
raw = re.sub(r"^```\s*", "", raw)
raw = re.sub(r"\s*```$", "", raw)

vocab = json.loads(raw)
out_path = paths.VOCAB_PATH
out_path.write_text(json.dumps(vocab, indent=2))
print("Curated Domain Vocabulary extracted successfully!")
print(json.dumps(vocab, indent=2))
