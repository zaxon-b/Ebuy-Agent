"""Four-group EvalCase contract for Canonical and Exploratory suites."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


UserAct = Literal[
    "request_refund", "provide_order_id", "correct_order_id", "confirm_order",
    "confirm_refund", "reject_refund", "other",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseMeta(StrictModel):
    id: str
    level: Literal["Easy", "Medium", "Hard"]
    description: str
    tags: list[str] = Field(default_factory=list)
    category: str = "C1"
    rule_sources: dict[str, str] = Field(default_factory=dict)
    # 难度观测标签（0-5，由脚本自动算，仅报告统计，不参与分类判定）
    difficulty_score: int = Field(default=0, ge=0, le=5)


class ToolErrorFault(StrictModel):
    type: Literal["tool_error"]
    tool: str
    trigger_call: int = Field(default=1, ge=1)
    fail_times: int | None = Field(default=None, ge=1)
    error: dict[str, Any]


class EmptyResultFault(StrictModel):
    type: Literal["empty_result"]
    tool: str
    trigger_call: int = Field(default=1, ge=1)
    fail_times: int | None = Field(default=None, ge=1)
    results: list[Any] = Field(default_factory=list)


FaultSpec = Annotated[
    Union[ToolErrorFault, EmptyResultFault],
    Field(discriminator="type"),
]


class RunSpec(StrictModel):
    modes: list[Literal["single", "multi"]] = Field(
        default_factory=lambda: ["single", "multi"]
    )
    seed_id: str = "demo-v1"
    user_id: str = "user-demo"
    initial_state_patch: dict[str, Any] = Field(default_factory=dict)
    faults: list[FaultSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_modes(self):
        if not self.modes or len(self.modes) != len(set(self.modes)):
            raise ValueError("run.modes 不能为空或重复")
        return self


class UserTurn(StrictModel):
    text: str
    acts: list[UserAct] = Field(default_factory=list)


class StaticDialogue(StrictModel):
    type: Literal["static"]
    turns: list[UserTurn] = Field(min_length=1)


class FSMDialogue(StrictModel):
    type: Literal["fsm"]
    start: str
    states: dict[str, Any]


class LLMDialogue(StrictModel):
    type: Literal["llm"]
    goal: str
    persona: str
    private_state: dict[str, Any] = Field(default_factory=dict)
    disclosure_rules: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)


DialogueSpec = Annotated[
    Union[StaticDialogue, FSMDialogue, LLMDialogue],
    Field(discriminator="type"),
]


class ExpectedToolCall(StrictModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class StateAssertion(StrictModel):
    table: Literal["orders", "products", "refunds"]
    op: Literal["eq", "count_eq"] = "eq"
    value: Any
    where: dict[str, Any]
    field: str | None = None


class ResponseRubric(StrictModel):
    must_include_facts: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    required_abstention: bool = False
    abstention_patterns: list[str] = Field(default_factory=list)
    forbidden_claim_patterns: list[str] = Field(default_factory=list)
    expected_clarification: bool | None = None
    expected_requires_human: bool | None = None

    @model_validator(mode="after")
    def validate_abstention(self):
        if self.required_abstention and not self.abstention_patterns:
            raise ValueError("required_abstention=true 时必须提供 abstention_patterns")
        return self


class ExpectedOutcome(StrictModel):
    tool_paths: list[list[ExpectedToolCall]] = Field(default_factory=lambda: [[]])
    forbidden_tools: list[str] = Field(default_factory=list)
    final_state: list[StateAssertion] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    reply: ResponseRubric = Field(default_factory=ResponseRubric)
    sop_ref: str | None = None
    # V2: 顺序约束 "strict"(默认，逐位相等) / "loose"(允许交错，调用集合对即可)
    order_constraint: Literal["strict", "loose"] = "strict"
    # 混合 case 覆盖的能力类别（回链专项）
    covers: list[str] = Field(default_factory=list)
    # C7 专用：即使位于 AUXILIARY_TOOLS 也计入必须出现（如 ["load_skill"]）
    required_tools: list[str] = Field(default_factory=list)
    # SOP 合法扩展工具：本 case 中这些工具允许重复/额外调用（如多次 search_knowledge、
    # 换词重搜 query_product、查单后补查物流），评测时超出参考路径的部分折叠掉，不算冗余。
    extendable_tools: list[str] = Field(default_factory=list)


class EvalCase(StrictModel):
    """A Case has four interview-level concepts: meta/run/dialogue/expected."""

    meta: CaseMeta
    run: RunSpec
    dialogue: DialogueSpec
    expected: ExpectedOutcome

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def level(self) -> str:
        return self.meta.level

    @property
    def description(self) -> str:
        return self.meta.description

    @property
    def tags(self) -> list[str]:
        return self.meta.tags

    @property
    def modes(self) -> list[str]:
        return list(self.run.modes)

    @property
    def simulator_mode(self) -> str:
        return self.dialogue.type

    @property
    def turn_texts(self) -> list[str]:
        if isinstance(self.dialogue, StaticDialogue):
            return [turn.text for turn in self.dialogue.turns]
        return []
