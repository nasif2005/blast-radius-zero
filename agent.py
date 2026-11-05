# agent.py

import os
from dotenv import load_dotenv
from openai import OpenAI

from sandbox_launcher_v2 import run_sandbox

load_dotenv()

api_key = os.getenv("VULTR_API_KEY")
if not api_key:
    raise RuntimeError("VULTR_API_KEY is missing")

client = OpenAI(
    api_key=api_key,
    base_url=os.getenv(
        "VULTR_BASE_URL",
        "https://api.vultrinference.com/v1"
    ),
    timeout=60.0,
    max_retries=1,
)


def generate_code(user_request: str) -> str:
    """Generate Python code using Vultr Serverless Inference."""

    response = client.chat.completions.create(
        model=os.getenv("VULTR_MODEL", "glm-5.3-flash"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Python code generator. "
                    "Return only executable Python 3 code. "
                    "Do not use Markdown code fences. "
                    "Do not include explanations. "
                    "Use only the Python standard library."
                ),
            },
            {
                "role": "user",
                "content": user_request,
            },
        ],
        max_tokens=1024,
    )

    code = response.choices[0].message.content

    if not code or not code.strip():
        raise RuntimeError("The model returned empty code")

    code = code.strip()

    # Handle occasional Markdown code fences.
    if code.startswith("```"):
        lines = code.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines).strip()

    # Check syntax without executing the generated code.
    compile(code, "<generated>", "exec")

    return code


def execute_request(user_request: str) -> dict:
    """Generate code, execute in Docker, and return results."""

    code = generate_code(user_request)

    print("\n--- Generated Python Code ---")
    print(code)

    print("\n--- Executing in Docker Sandbox ---")

    result = run_sandbox(code)

    return {
        "request": user_request,
        "generated_code": code,
        "execution": result,
    }


if __name__ == "__main__":
    request = (
        "Write Python code to calculate factorial(5) "
        "and print the result."
    )

    result = execute_request(request)

    print("\n--- Sandbox Execution Result ---")
    print(result["execution"])