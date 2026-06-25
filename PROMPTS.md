# Prompts

> Central place for the agent's prompts. Scaffold — fill in as personas and
> scenarios are designed.

## Base system prompt

The shared instructions every outbound call starts from (persona, tone,
guardrails, how to open and close the call).

```
TODO: base system prompt.
```

## Scenario prompts

Per-scenario overlays layered on top of the base prompt. Each scenario in
`scenarios/` should map to an entry here.

### <scenario-name>

- **Goal:** TODO
- **Opening line:** TODO
- **Success criteria:** TODO
- **Prompt:**

```
TODO: scenario-specific instructions.
```

## Notes

- Keep prompts versioned alongside code so call behavior is reproducible.
- Record which prompt version produced each recording in `analysis/`.
