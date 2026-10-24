# ThinkLens

A small media-literacy prototype that highlights persuasive language and explains possible rhetorical effects. It supports pasted text, public article links, interactive highlights, category filters, and an overall-impression card.

## Run locally

Requires Python 3. No Python packages need installing.

```sh
python server.py
```

Open [ThinkLens locally](http://127.0.0.1:8765/ThinkLens.html).

On Windows, you can also run `Start-ThinkLens.cmd`.

## Live AI or offline demo

Live AI requires the official [Codex CLI](https://learn.chatgpt.com/docs/non-interactive-mode) installed on your PATH and signed in with your own ChatGPT account:

```sh
codex login
```

Click **Check connection** in ThinkLens and choose **Live AI**. Each person running a copy must sign in with their own account. Publishing this code does not share the author's ChatGPT access.

Alternatively, select **Offline demo** to use the included phrase rules. Offline mode also works by opening `ThinkLens.html` directly; article import and live AI require the local server.

## Tests

```sh
python -m unittest discover -s tests -v
```

## Interpretation and privacy

- Findings are interpretations of language, not proof of intentions, dishonesty, or factual accuracy.
- Overall-impression levels use the proportion of sentences with detected cues. They are presentation thresholds, not validated influence measurements.
- Live mode sends text to OpenAI through Codex under the signed-in account's applicable policies and limits.
- ThinkLens does not intentionally save submitted text, results, URLs, or account credentials. Codex manages its own sign-in.
- Article imports may fail, return previews, omit content, or include unrelated text. Long text is shortened and labeled.
- The server binds to `127.0.0.1` for personal local use. It is not designed to be exposed as a public AI service.

See [README.txt](README.txt) for implementation details and [START-HERE.txt](START-HERE.txt) for presentation instructions.
