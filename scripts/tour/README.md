# Tour screenshots

The tour (`src/ui/web/js/tour.js`) shows PNGs from `src/ui/web/tour/`. They are captured from
made-up meetings, never real data. To regenerate after a UI change:

```bash
D=$(mktemp -d)
VOICECOACH_DATA_DIR=$D .venv/bin/python scripts/tour/seed_demo.py "$PWD/python"
VOICECOACH_DATA_DIR=$D VOICECOACH_API_TOKEN=demo-tour-token CORA_BUILD_VARIANT=team \
  .venv/bin/python python/server.py --port 18432 &
node_modules/.bin/electron scripts/tour/capture-tour.js "$PWD" http://127.0.0.1:18432/ demo-tour-token "$D/shots"
cp "$D"/shots/{new-note,notes,beta-settings,call-prompt}.png src/ui/web/tour/
kill %1
```

Run it without `CORA_BETA_RECEIVER_URL` / `CORA_BETA_TOKEN` set, so the demo server sends nothing.
