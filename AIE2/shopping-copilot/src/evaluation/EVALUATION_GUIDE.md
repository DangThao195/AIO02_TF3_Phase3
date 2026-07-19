# Shopping Copilot - Evaluation Guide

This guide explains the Evaluation Pipeline for the Shopping Copilot, which uses an **LLM-as-a-Judge** architecture to ensure the highest quality of reasoning, factuality, and safety.

## 1. Overview of the Evaluation Pipeline

The evaluation pipeline (`src/evaluation/eval_baselines.py`) simulates user interactions by sending predefined test cases to the Agent and evaluating the response. 

We use **Amazon Nova Micro / Meta Llama 3** (configured via `BEDROCK_MODEL_ID` / `JUDGE_MODEL_ID`) as the autonomous judge.

### Reference-Based Evaluation (RAG Evaluation)
To prevent the LLM Judge from hallucinating or penalizing the Agent unfairly, the Agent is configured to expose its internal state during testing:
1. **Parsed Intent (L1)**: What the Agent thought the user wanted.
2. **Database Evidence (L3/L4)**: The exact JSON results returned from the database.
3. **Final Response (L5)**: The text the Agent generated.

The LLM Judge receives all three components. It verifies that the **Parsed Intent** correctly matches the user's input, and that the **Final Response** is strictly faithful to the **Database Evidence** (no hallucination).

## 2. Test Suites

The test cases are divided into two main files:

### A. Guardrails (`baseline_guardrails.json`)
Tests the Agent's ability to defend against malicious inputs and policy violations.
- **`prompt_injection`**: Attempts to manipulate the system prompt, make the AI swear, or act as a different persona (e.g., DAN).
- **`pii_leakage`**: Tests if the Agent correctly redacts or refuses to process emails, credit cards, or SSNs.
- **`action_guard`**: Tests if the Agent strictly refuses forbidden actions (like deleting the cart or placing an order without confirmation).

### B. Responses (`baseline_response.json`)
Tests the Agent's conversational and shopping capabilities.
- **`single_intent`**: Standard shopping queries (search, list, price filtering).
- **`contextual`**: Follow-up questions relying on chat history ("compare those two", "add the first one").
- **`multilingual`**: Queries in Vietnamese, Spanish, French, etc. to ensure the Agent responds in the correct language.
- **`complex_logic`**: Multi-step reasoning queries.
- **`factuality`**: Queries asking for fabricated specs (e.g., "Does this telescope have 5G?"). The Agent must admit lack of information, not invent specs.

## 3. Running Evaluations

The evaluation script is purely LLM-based. You do not need to pass the `--llm` flag manually anymore.

**Evaluate Guardrails (10 cases):**
```powershell
python src/evaluation/eval_baselines.py --file baseline_guardrails.json --max 10
```

**Evaluate Responses (10 cases):**
```powershell
python src/evaluation/eval_baselines.py --file baseline_response.json --max 10
```

## 4. Understanding the Report

After execution, a report (e.g., `baseline_response_report.json`) is generated.
- **`passed_cases` / `total_cases`**: The overall pass rate.
- **`failed_samples`**: A detailed list of all failed cases, including the `judge_reason` (why the LLM Judge failed it) and the exact `reply` from the Agent. Use this to continuously tune the Agent's `SYSTEM_PROMPT`.
