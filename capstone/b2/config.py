"""B2 settings. Every decision field is required and has no default.

The shipped file ``capstone/run/configs/b2_unfrozen.json`` is status
``UNFROZEN``. ``proposed`` in that file is a comment. ``load`` never copies
it into a live field. Launch raises ``B2ConfigError`` until a human sets
``status`` to ``SET`` and sets every live field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Arm = Literal["b1_reject", "random_control"]
Policy = Literal["flag_keep_original", "abstain"]
TokenMethod = Literal["chars_div_4"]
LIVE_FIELDS = (
    "arm",
    "recovery_step_cap",
    "max_recovery_tool_calls",
    "max_recovery_llm_calls",
    "recovery_timeout_s",
    "max_resume_prompt_tokens",
    "prompt_token_count_method",
    "control_seed",
    "matched_trigger_count",
    "on_reject",
    "on_cap_hit",
    "on_error",
    "on_insufficient",
)


class B2ConfigError(RuntimeError):
    """B2 refused to launch. The message is the whole reason."""


class B2Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    arm: str | None
    recovery_step_cap: int | None
    max_recovery_tool_calls: int | None
    max_recovery_llm_calls: int | None
    recovery_timeout_s: float | None
    max_resume_prompt_tokens: int | None
    prompt_token_count_method: str | None
    control_seed: int | None
    matched_trigger_count: int | None
    on_reject: str | None
    on_cap_hit: str | None
    on_error: str | None
    on_insufficient: str | None
    # Documentation only. validate_launch does not read this.
    note: str = ""
    proposed: dict[str, Any] | None = Field(default=None)

    @classmethod
    def load(cls, path: str | Path) -> B2Config:
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise B2ConfigError(
                f"B2 REFUSING TO LAUNCH: cannot read config {path}: {exc}"
            ) from exc
        try:
            cfg = cls.model_validate(raw)
        except Exception as exc:
            raise B2ConfigError(
                f"B2 REFUSING TO LAUNCH: {path} is not a complete B2 config: {exc}"
            ) from exc
        cfg.validate_launch(source=str(path))
        return cfg

    def validate_launch(self, source: str = "B2 config") -> None:
        if self.status != "SET":
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: "
                f"{source} status is {self.status!r}, not 'SET'. "
                "UNFROZEN means the decision fields are unset. "
                "The 'proposed' object is a comment and is not applied."
            )
        missing = [name for name in LIVE_FIELDS if getattr(self, name) is None]
        # control_seed and matched_trigger_count are null on the b1_reject arm
        # and required on the random_control arm. Checked below, not here.
        missing = [
            name
            for name in missing
            if name not in ("control_seed", "matched_trigger_count")
        ]
        if missing:
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: "
                f"{source} has unset decision fields: {', '.join(missing)}. "
                "No default is filled in. 'proposed' is not a live value."
            )
        self._check_arm()
        self._check_caps()
        self._check_policy("on_reject", self.on_reject)
        self._check_policy("on_cap_hit", self.on_cap_hit)
        self._check_policy("on_error", self.on_error)
        self._check_policy("on_insufficient", self.on_insufficient)
        if self.prompt_token_count_method not in ("chars_div_4",):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: prompt_token_count_method must be "
                "'chars_div_4' (no model tokenizer is bundled). "
                f"Got {self.prompt_token_count_method!r}."
            )

    def _check_arm(self) -> None:
        if self.arm not in ("b1_reject", "random_control"):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: arm must be 'b1_reject' or "
                f"'random_control'. Got {self.arm!r}."
            )
        if self.arm == "b1_reject":
            if self.control_seed is not None or self.matched_trigger_count is not None:
                raise B2ConfigError(
                    "B2 REFUSING TO LAUNCH: b1_reject does not use control_seed "
                    "or matched_trigger_count. Set both to null. "
                    "A number there would look like a control-arm decision on "
                    "the treatment arm."
                )
            return
        if isinstance(self.control_seed, bool) or not isinstance(self.control_seed, int):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: random_control requires control_seed "
                f"as an int. Got {self.control_seed!r}."
            )
        if (
            isinstance(self.matched_trigger_count, bool)
            or not isinstance(self.matched_trigger_count, int)
            or self.matched_trigger_count < 0
        ):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: random_control requires "
                "matched_trigger_count as an int >= 0 (the B1 flag count). "
                f"Got {self.matched_trigger_count!r}. It is not inferred."
            )

    def _check_caps(self) -> None:
        _int(self.recovery_step_cap, "recovery_step_cap", minimum=1)
        _int(self.max_recovery_tool_calls, "max_recovery_tool_calls", minimum=0)
        _int(self.max_recovery_llm_calls, "max_recovery_llm_calls", minimum=1)
        _int(self.max_resume_prompt_tokens, "max_resume_prompt_tokens", minimum=1)
        if (
            isinstance(self.recovery_timeout_s, bool)
            or not isinstance(self.recovery_timeout_s, (int, float))
            or self.recovery_timeout_s <= 0
        ):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: recovery_timeout_s must be a number "
                f"> 0. Got {self.recovery_timeout_s!r}."
            )

    def _check_policy(self, name: str, value: str | None) -> None:
        if value not in ("flag_keep_original", "abstain"):
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: "
                f"{name} must be 'flag_keep_original' or 'abstain'. Got {value!r}."
            )

    def live_dict(self) -> dict[str, Any]:
        """Live fields only. ``proposed`` and ``note`` are omitted."""
        return {name: getattr(self, name) for name in ("status", *LIVE_FIELDS)}


def _int(value: object, name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise B2ConfigError(
            f"B2 REFUSING TO LAUNCH: {name} must be an int >= {minimum}. Got {value!r}."
        )


def count_prompt_tokens(text: str, method: str) -> int:
    if method == "chars_div_4":
        return (len(text) + 3) // 4
    raise B2ConfigError(
        f"B2 REFUSING TO LAUNCH: unknown prompt_token_count_method {method!r}."
    )
