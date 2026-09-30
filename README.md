# English Coach

Ek chhota web app jahan koi bhi English sentence bolke bhej sakta hai, aur app usse sahi karke wapas awaaz mein sunata hai. Sirf apne trusted logon (jaise brother) ke liye — ek access code ke peeche band hai.

## Pipeline

```
Mic se recording (browser, WAV 16kHz)
        |
Google Speech-to-Text  ->  transcript
        |
Groq LLM  ->  { corrected, explanation, reply }
        |
ElevenLabs TTS (fallback: edge-tts -> browser voice)
```

## Files

| File | Kaam |
|---|---|
| `main.py` | FastAPI backend — STT, LLM, TTS teeno yahin jude hain |
| `index.html` | Poora frontend, ek hi page — mic button, red/yellow correction view |
| `requirements.txt` | Python dependencies |
| `render.yaml` | Render Blueprint (ek click deploy ke liye) |
| `.env.example` | Local testing ke liye env variables ka template |

## 1. Local setup

### Google Cloud (Speech-to-Text)

1. [console.cloud.google.com](https://console.cloud.google.com) pe naya project banao.
2. **Speech-to-Text API** enable karo.
3. **IAM & Admin -> Service Accounts -> Create Service Account.**
4. Usme **Cloud Speech Client** role do.
5. **Keys -> Add Key -> JSON**, file download hogi. Isse `english-coach/service-account.json` naam se save karo.
6. Billing account link karna padega (60 min/month free hai, uske baad charge lagta hai).

### Groq

1. [console.groq.com](https://console.groq.com) pe account banao, API key generate karo.
2. **Models** page pe current chat model ka naam check kar lo (naam badalte rehte hain).

### ElevenLabs

1. [elevenlabs.io](https://elevenlabs.io) pe account banao.
2. **Profile -> API Keys** se key nikalo.
3. Koi voice choose karke uski **Voice ID** copy kar lo (default page pe already ek voice ID diya hua hai, wo bhi chalega).

### Install aur run

```bash
cd english-coach
pip install -r requirements.txt
cp .env.example .env
```

`.env` mein values bharo:

```
ACCESS_CODE=koi-bhi-secret-code
GROQ_API_KEY=...
ELEVEN_API_KEY=...
GOOGLE_APPLICATION_CREDENTIALS=service-account.json
```

Run karo:

```bash
uvicorn main:app --reload
```

Browser mein `http://localhost:8000` kholo. Mic sirf `localhost` ya `https` pe chalta hai, isliye local testing mein dikkat nahi aayegi.

## 2. Render pe deploy

1. Is folder ko ek **private** GitHub repo mein push karo (`.gitignore` mein `.env` aur `service-account.json` pehle se excluded hain, toh accidentally push nahi honge).
2. [render.com](https://render.com) pe **New -> Blueprint** choose karo aur repo connect karo — `render.yaml` se sab settings apne aap aa jayengi. (Blueprint na dikhe toh **New -> Web Service** se bhi kar sakte ho: Build command `pip install -r requirements.txt`, Start command `uvicorn main:app --host 0.0.0.0 --port $PORT`.)
3. Environment mein 4 variables bharo:
   - `ACCESS_CODE`
   - `GROQ_API_KEY`
   - `ELEVEN_API_KEY`
   - `GOOGLE_CREDENTIALS_JSON` — service-account.json ka **poora content** copy-paste karo (file nahi, seedha JSON text)
4. Deploy hone do. `https://<app-name>.onrender.com` pe app live ho jayegi.
5. Link aur access code brother ko bhej do.

## Dhyan rakhne wali baatein

- **Render free plan** thodi der idle rehne ke baad so jati hai — pehla request slow ho sakta hai.
- **Google STT free tier**: 60 min/month, uske baad paisa lagta hai. Google Cloud console mein budget alert laga lena.
- **ElevenLabs free tier**: ~10,000 characters/month. Limit khatam hote hi app apne aap `edge-tts` (free) pe switch ho jati hai, aur wo bhi fail ho toh browser ki built-in awaaz use hoti hai.
- `usage.json` sirf best-effort counter hai — Render free plan pe restart hone par reset ho jata hai, isse 100% bharosa mat karna.
- Agar Groq model error de, to `main.py` mein `GROQ_MODEL` env variable set karke naya model name daal sakte ho.
