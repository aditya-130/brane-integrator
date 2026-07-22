GPT4O_INPUT_PER_1M = 2.50
GPT4O_OUTPUT_PER_1M = 10.00


def summarize_usage(usage_log: list[dict]) -> dict:
    if not usage_log:
        return {"n_calls": 0}

    costs = []
    for entry in usage_log:
        cost = (
            entry["prompt_tokens"] / 1_000_000 * GPT4O_INPUT_PER_1M
            + entry["completion_tokens"] / 1_000_000 * GPT4O_OUTPUT_PER_1M
        )
        costs.append(cost)

    n = len(usage_log)
    total_prompt = sum(e["prompt_tokens"] for e in usage_log)
    total_completion = sum(e["completion_tokens"] for e in usage_log)
    total_cost = sum(costs)

    return {
        "n_calls": n,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_cost_usd": round(total_cost, 5),
        "avg_cost_per_call_usd": round(total_cost / n, 6),
        "min_cost_per_call_usd": round(min(costs), 6),
        "max_cost_per_call_usd": round(max(costs), 6),
        "avg_prompt_tokens": round(total_prompt / n, 1),
        "avg_completion_tokens": round(total_completion / n, 1),
    }


def print_usage_summary(usage_log: list[dict], label: str = "LLM usage") -> dict:
    summary = summarize_usage(usage_log)
    if summary["n_calls"] == 0:
        print(f"\n{label}: no calls recorded")
        return summary
    print(f"\n=== {label} ===")
    print(f"Calls:                {summary['n_calls']}")
    print(f"Total cost:           ${summary['total_cost_usd']}")
    print(f"Avg cost/call:        ${summary['avg_cost_per_call_usd']}")
    print(f"Min/max cost/call:    ${summary['min_cost_per_call_usd']} / ${summary['max_cost_per_call_usd']}")
    print(f"Avg prompt tokens:    {summary['avg_prompt_tokens']}")
    print(f"Avg completion tokens:{summary['avg_completion_tokens']}")
    return summary
