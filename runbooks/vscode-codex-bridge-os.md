# VSCode Bridge 執行流程

- Directly run command.
- Wait for every step.
- After writing `bridge/res.json`, go back to step 2.

## 1. Start app in VSCode mode

Run command:

```bash
test -d .venv || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --vscode
```

Wait until the app shows it is running on `http://127.0.0.1:8000`.

## 2. Open app

Run command:

```bash
open http://127.0.0.1:8000
```

## 3. Create a sub-agent to run command and wait for  at least `300` seconds
(1) Wait for bridge prompt update

Run command and wait until it shows `Done`:

```bash
.venv/bin/python bridge/hook.py 300
```

-

(2) Read prompt

Run command:

```bash
cat bridge/prompt.md
```

Read the full prompt and generate the required JSON output.

(3) Save result

Save the generated JSON output to `bridge/res.json`, then run command:

```bash
.venv/bin/python -m json.tool bridge/res.json
```

## Step4 Go Back to Step3 and create a new sub-agent
Wait until the command succeeds. 
If timeout then finish else go back to step 3.
