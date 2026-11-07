
# Blast Radius Zero
### Secure Execution of AI-Generated Python Code on Vultr Cloud

**Blast Radius Zero** is a security-focused AI execution prototype developed for the Vultr Hackathon. It enables users to generate Python programs from natural-language requests using **Vultr Serverless Inference** and run them inside resource-restricted Docker containers.

The project explores a central security question:

> How can we execute AI-generated code while minimizing its ability to affect the host system, access sensitive resources, or disrupt other services?

## Demo Video

[Watch the Blast Radius Zero demonstration on YouTube](https://youtu.be/3Nk_YBBAdn0)

## Key Features

- Natural-language-to-Python generation using Vultr Serverless Inference
- FastAPI backend and browser-based user interface
- Two-VM deployment separating application logic from code execution
- Private Vultr VPC communication with token-based worker authentication
- Resource-restricted Docker execution
- Execution timeouts, bounded output, and container cleanup
- Automated sandbox security tests

## System Architecture

The deployed prototype consists of two Vultr virtual machines.

**VM1 — AI Agent and Application Server**
- Hosts the FastAPI backend and browser interface.
- Receives natural-language programming requests.
- Uses Vultr Serverless Inference to generate Python code.
- Forwards generated code to the execution worker.

**VM2 — Execution Worker**
- Hosts an authenticated FastAPI worker service.
- Receives generated code over a private Vultr VPC.
- Launches a restricted Docker container for execution.
- Returns standard output, standard error, exit status, and execution metadata.

### Execution Workflow

```text
User / Browser
      |
      v
VM1: FastAPI Application
      |
      v
Vultr Serverless Inference
      |
      v
Generated Python Code
      |
      | Private VPC + Token Authentication
      v
VM2: FastAPI Execution Worker
      |
      v
Restricted Docker Container
      |
      v
Execution Results
      |
      v
VM1 -> Browser
```

Vultr Serverless Inference is a managed API accessed by VM1, not a service running inside the private VPC.

## Docker Sandbox Security Controls

| Control | Implementation |
|---|---|
| Network isolation | `--network none` |
| Read-only root filesystem | `--read-only` |
| Non-root execution | `--user 65534:65534` |
| Linux capability restriction | `--cap-drop ALL` |
| Privilege escalation restriction | `--security-opt no-new-privileges` |
| Memory limit | 128 MB |
| CPU limit | 0.5 CPU |
| Process limit | 64 |
| Execution timeout | 10 seconds |
| Captured output limit | 64 KiB combined |
| Maximum concurrent executions | 2 per launcher process |
| Container cleanup | Forced removal with verification |

These controls provide defense in depth, but Docker containers share the host operating-system kernel and do not constitute a complete security boundary against all attacks.

## Security Evaluation

The sandbox was evaluated using 12 automated tests on the execution worker.

| Test | Result |
|---|---|
| Normal execution | PASS |
| Runtime exception handling | PASS |
| Execution timeout | PASS |
| Memory limit | PASS |
| Network isolation | PASS |
| Read-only root filesystem | PASS |
| Host path not mounted | PASS |
| Container cleanup | PASS |
| Standard output limit | PASS |
| Standard error limit | PASS |
| Combined output limit | PASS |
| Busy-request rejection | PASS |

**Latest recorded result: 12/12 tests passed in 15.522 seconds.**

These tests validate specific implemented restrictions under the tested conditions. They do not establish complete resistance to container escape or other attacks.

### Run the Security Tests

Requires Docker and the `python:3.11-slim` image.

```bash
docker pull python:3.11-slim
python3 -m unittest -v test_security_v3.py
```

## Example Demonstration

**User request:**

```text
Write Python code to calculate the factorial of five and print the result.
```

**Example generated Python code:**

```python
import math

result = math.factorial(5)
print(result)
```

**Expected output:**

```text
120
```

The application displays generated code, standard output, standard error, execution duration, exit code, timeout status, and cleanup status.

One successful demonstration reported approximately 0.4 seconds of sandbox execution time. This is an individual observation, not a throughput or latency benchmark.

## Technology Stack

- **Cloud:** Vultr Cloud Compute and Private VPC
- **AI:** Vultr Serverless Inference
- **Backend:** Python, FastAPI, Pydantic
- **Execution:** Docker, Python 3.11
- **Operating System:** Ubuntu Linux
- **Testing:** Python unittest
- **Frontend:** HTML and JavaScript

## Repository Structure

```text
blast-radius-zero/
├── agent.py
├── main.py
├── sandbox_launcher_v3.py
├── test_security_v3.py
├── evaluate_security.py
└── frontend/
    └── index.html
```

### Deployment Reproducibility Note

The current public repository contains the original local Docker execution integration in `agent.py`.

The demonstrated two-VM deployment uses an updated VM1 agent and a separate `worker_api.py` service on VM2. Those deployment-specific components need to be synchronized with this repository before the complete distributed architecture can be reproduced from the published source.

Do not commit API keys, worker authentication tokens, `.env` files, or private SSH keys.

## Local Development

Clone the repository:

```bash
git clone https://github.com/nasif2005/blast-radius-zero.git
cd blast-radius-zero
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the Python dependencies:

```bash
pip install fastapi uvicorn openai python-dotenv
```

Configure Vultr Serverless Inference credentials securely:

```text
VULTR_API_KEY=<your-api-key>
VULTR_BASE_URL=https://api.vultrinference.com/v1
VULTR_MODEL=glm-5.3-flash
```

Place these values in a local `.env` file that is excluded from version control.

Install and start Docker, then pull the sandbox image:

```bash
docker pull python:3.11-slim
```

Start the local development application:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000` on the development machine.

**Security warning:** The local development configuration is not intended for public exposure. Do not grant untrusted Internet users direct access to a Docker-backed code-execution endpoint without additional protection.

## Current Limitations

- Docker shares the host kernel.
- The worker service currently operates with elevated host privileges.
- VM-to-VM communication uses token-authenticated HTTP over a private VPC, without transport-layer encryption.
- The prototype is not a production-grade multi-tenant sandbox.
- Additional adversarial testing and stronger isolation are necessary.
- The distributed deployment code has not yet been fully synchronized with the public repository.

## Future Work

- Explore microVM-based execution isolation.
- Reduce execution-worker privileges.
- Add encrypted and mutually authenticated worker communication.
- Expand automated adversarial evaluation.
- Improve observability, rate limiting, and operational safeguards.
- Publish complete reproducible deployment instructions.

## Project Links

- **Repository:** https://github.com/nasif2005/blast-radius-zero
- **Video demonstration:** https://youtu.be/3Nk_YBBAdn0

## License

No license has been declared yet. A license file can be added after selecting appropriate reuse terms.
