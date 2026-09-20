"""Criteria Builder：原始要求 → 可编辑草稿；发布必须人工确认且不可覆盖。

纪律：
- 草稿不是正式标准；publish 生成全新 (rubric_id, revision)，旧文件永不改写；
- plain_text/markdown 来源的评分语义必须由 scoring_sources 的逐字片段支持：
  数值独立 token（20 不命中 120）、档位 label/description/score、锚点都要能定位；
  支持不了就草稿丢弃、publish 拒绝（confirmed 不能豁免）；
- manual 用户自撰评分规则、rubric_json 结构化原文不走外部 provenance 校验；
- 模型不可用时仍可手工填 criteria 直接发布。
"""
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app import criteria_builder, llm, main, rubric_store
from app.contracts import CriterionDraft, RubricDraftRequest, RubricPublish

SOURCE_TEXT = (
    "一、技术实现：核心功能已实现并可运行。\n"
    "二、创新性：创新点需与现有做法对比。\n"
)


class StubComplete:
    """按序返回预设响应；记录调用，供「不得调用 LLM」断言。"""

    def __init__(self, replies=()):
        self.calls = []
        self._replies = list(replies)

    def __call__(self, settings, messages):
        self.calls.append(messages)
        return self._replies.pop(0) if self._replies else "{}"


def reply_of(title="校赛标准", criteria=None, aggregation=None, aggregation_source=None, extra=None):
    payload = {
        "title": title,
        "aggregation_rule": aggregation,
        "aggregation_rule_source": aggregation_source,
        "criteria": criteria,
    }
    if extra is not None:
        payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def criterion_payload(title="技术实现", requirement="核心功能已实现并可运行", evidence=None, **scoring):
    payload = {
        "title": title,
        "requirement": requirement,
        "required_evidence": evidence if evidence is not None else [],
        "scoring_sources": [],
        "max_score": None,
        "weight": None,
        "rubric_levels": None,
        "scoring_anchors": None,
    }
    payload.update(scoring)
    return payload


def request_of(text=SOURCE_TEXT, source_type="plain_text", source_name=None):
    return RubricDraftRequest(text=text, source_type=source_type, source_name=source_name)


def manual_publish(title="手工标准", criteria=None, source_type="manual", source_text="手工输入的原始要求", **provenance):
    drafts = criteria or [
        CriterionDraft(
            id="crit_manual_1",
            order=0,
            title="技术实现",
            requirement="核心功能已实现并可运行",
            required_evidence=["运行说明段落"],
        )
    ]
    return RubricPublish(
        title=title,
        source_note="用户手工整理",
        source_type=source_type,
        source_text=source_text,
        criteria=drafts,
        confirmed=True,
        **provenance,
    )


class ModelDraftTest(unittest.TestCase):
    """LLM 草稿路径：stub complete，零网络。"""

    def setUp(self) -> None:
        self._original_complete = llm.complete
        self._original_settings = llm.load_settings
        llm.load_settings = lambda: llm.LlmSettings("http://stub/v1", "stub-key", "stub-model", 1.0)
        self.complete = StubComplete()
        llm.complete = self.complete

    def tearDown(self) -> None:
        llm.complete = self._original_complete
        llm.load_settings = self._original_settings

    def test_model_draft_preserves_source_and_orders_criteria(self) -> None:
        self.complete._replies = [
            reply_of(
                criteria=[
                    criterion_payload(),
                    criterion_payload(title="创新性", requirement="创新点需与现有做法对比"),
                ]
            )
        ]

        draft = criteria_builder.draft_requirements(request_of(source_name="req.md"))

        self.assertTrue(draft.model_assisted)
        self.assertEqual(draft.source_text, SOURCE_TEXT)
        self.assertEqual((draft.source_type, draft.source_name), ("plain_text", "req.md"))
        self.assertEqual(draft.criteria[0].title, "技术实现")
        self.assertEqual([item.order for item in draft.criteria], [0, 1])
        self.assertEqual(len({item.id for item in draft.criteria}), 2)
        self.assertTrue(all(item.id.startswith("crit_") for item in draft.criteria))
        self.assertEqual(draft.criteria[1].required_evidence, [])
        self.assertEqual(len(self.complete.calls), 1)
        system, user = self.complete.calls[0]
        self.assertIn("JSON", system["content"])
        self.assertIn("严禁自行设计", system["content"])
        self.assertIn("核心功能已实现并可运行", user["content"])

    def test_scoring_semantics_are_preserved_when_source_grounded(self) -> None:
        text = (
            "一、技术实现：核心功能已实现并可运行。\n"
            "评分：满分 20 分，权重 30%。\n"
            "档位：优秀（18-20分）表现突出。\n"
            "聚合规则：加权求和。\n"
        )
        self.complete._replies = [
            reply_of(
                aggregation="加权求和",
                aggregation_source="聚合规则：加权求和",
                criteria=[
                    criterion_payload(
                        max_score=20,
                        weight=0.3,
                        rubric_levels=[
                            {"label": "优秀", "description": "表现突出", "score": 18},
                            {"label": "编造档位", "description": None, "score": 99},
                        ],
                        scoring_anchors=["满分 20 分", "不存在的锚点"],
                        scoring_sources=["评分：满分 20 分，权重 30%", "档位：优秀（18-20分）表现突出"],
                    )
                ],
            )
        ]

        draft = criteria_builder.draft_requirements(request_of(text=text))
        criterion = draft.criteria[0]

        self.assertEqual(criterion.max_score, 20)
        self.assertEqual(criterion.weight, 0.3)
        self.assertEqual(draft.aggregation_rule, "加权求和")
        self.assertEqual(draft.aggregation_rule_source, "聚合规则：加权求和")
        # 只有能逐字定位的档位/锚点保留；编造的档位与锚点被丢弃。
        self.assertEqual([level.label for level in criterion.rubric_levels], ["优秀"])
        self.assertEqual(criterion.rubric_levels[0].description, "表现突出")
        self.assertEqual(criterion.rubric_levels[0].score, 18)
        self.assertEqual(criterion.scoring_anchors, ["满分 20 分"])
        self.assertEqual(
            criterion.scoring_sources,
            ["评分：满分 20 分，权重 30%", "档位：优秀（18-20分）表现突出"],
        )

    def test_number_must_not_match_inside_longer_number(self) -> None:
        # 「120 个样本」里的 20 不是独立 token：不得认证模型虚构的 max_score=20。
        text = "一、技术实现：核心功能已实现并可运行。\n样本量 120 个。\n"
        self.complete._replies = [
            reply_of(
                criteria=[
                    criterion_payload(max_score=20, scoring_sources=["样本量 120 个"]),
                ]
            )
        ]

        criterion = criteria_builder.draft_requirements(request_of(text=text)).criteria[0]

        self.assertIsNone(criterion.max_score)
        self.assertIsNone(criterion.scoring_sources)

    def test_fabricated_level_description_is_dropped(self) -> None:
        # 只出现 label「优秀」不能自动认证虚构 description。
        text = "一、技术实现：核心功能已实现并可运行。\n评级：优秀。\n"
        self.complete._replies = [
            reply_of(
                criteria=[
                    criterion_payload(
                        rubric_levels=[{"label": "优秀", "description": "表现突出", "score": None}],
                        scoring_sources=["评级：优秀"],
                    )
                ]
            )
        ]

        criterion = criteria_builder.draft_requirements(request_of(text=text)).criteria[0]

        self.assertEqual([level.label for level in criterion.rubric_levels], ["优秀"])
        self.assertIsNone(criterion.rubric_levels[0].description)

    def test_scoring_absent_when_source_has_none(self) -> None:
        self.complete._replies = [reply_of(criteria=[criterion_payload()])]

        draft = criteria_builder.draft_requirements(request_of())

        criterion = draft.criteria[0]
        self.assertIsNone(criterion.max_score)
        self.assertIsNone(criterion.weight)
        self.assertIsNone(criterion.rubric_levels)
        self.assertIsNone(criterion.scoring_anchors)
        self.assertIsNone(criterion.scoring_sources)
        self.assertIsNone(draft.aggregation_rule)

    def test_invented_scoring_is_stripped_without_source_anchor(self) -> None:
        # 源文本没有评分语义，模型编造的分数/档位/锚点（及其伪造来源片段）全部不得进入草稿。
        self.complete._replies = [
            reply_of(
                aggregation="加权求和",
                aggregation_source="聚合规则：加权求和",
                criteria=[
                    criterion_payload(
                        max_score=20,
                        weight=0.5,
                        rubric_levels=[{"label": "优秀", "description": None, "score": 90}],
                        scoring_anchors=["达到 90% 以上"],
                        scoring_sources=["不存在的来源片段"],
                    )
                ],
            )
        ]

        draft = criteria_builder.draft_requirements(request_of())
        criterion = draft.criteria[0]

        self.assertIsNone(criterion.max_score)
        self.assertIsNone(criterion.weight)
        self.assertIsNone(criterion.rubric_levels)
        self.assertIsNone(criterion.scoring_anchors)
        self.assertIsNone(criterion.scoring_sources)
        self.assertIsNone(draft.aggregation_rule)
        self.assertIsNone(draft.aggregation_rule_source)

    def test_malformed_model_replies_are_rejected(self) -> None:
        cases = {
            "not_json": "不是 JSON",
            "array": "[]",
            "extra_top_key": reply_of(criteria=[criterion_payload()], extra={"unexpected": True}),
            "missing_criteria": json.dumps({"title": "x"}, ensure_ascii=False),
            "blank_title": reply_of(title="   ", criteria=[criterion_payload()]),
            "criteria_not_list": json.dumps({"title": "x", "criteria": {}}, ensure_ascii=False),
            "criterion_missing_requirement": reply_of(criteria=[{"title": "只有标题"}]),
            "criterion_extra_field": reply_of(criteria=[criterion_payload(confidence=0.9)]),
            "too_many_criteria": reply_of(
                criteria=[criterion_payload(title=f"要求 {index}") for index in range(51)]
            ),
        }
        for name, reply in cases.items():
            with self.subTest(name=name):
                self.complete._replies = [reply]
                with self.assertRaises(llm.LlmInvalidResponse):
                    criteria_builder.draft_requirements(request_of())

    def test_unconfigured_model_raises_without_calling_llm_and_manual_publish_works(self) -> None:
        llm.load_settings = lambda: llm.LlmSettings(None, None, None, 1.0)

        with self.assertRaises(llm.LlmNotConfigured):
            criteria_builder.draft_requirements(request_of())
        self.assertEqual(self.complete.calls, [])

        # 模型不可用时，用户手工填 criteria（manual 来源）仍可发布。
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rubric_store.set_index({})
            try:
                rubric = rubric_store.publish(manual_publish(), directory)
            finally:
                rubric_store.reset_index()
        self.assertEqual(rubric.criteria[0].id, "crit_manual_1")
        self.assertEqual(rubric.source_text, "手工输入的原始要求")
        self.assertFalse(rubric.model_assisted)


class StructuredJsonDraftTest(unittest.TestCase):
    """结构化 Rubric JSON：确定性转写，不调用模型，评分语义原样保留。"""

    def setUp(self) -> None:
        self._original_complete = llm.complete
        self.complete = StubComplete()
        llm.complete = self.complete

    def tearDown(self) -> None:
        llm.complete = self._original_complete

    def test_structured_json_preserves_scoring_and_ids_without_llm(self) -> None:
        source = json.dumps(
            {
                "id": "rubric_source",
                "revision": 1,
                "title": "结构化标准",
                "source_note": "来自用户文件",
                "aggregation_rule": "加权求和",
                "aggregation_rule_source": "加权求和",
                "criteria": [
                    {
                        "id": "crit_keep",
                        "title": "技术实现",
                        "requirement": "核心功能已实现并可运行",
                        "required_evidence": ["运行说明段落"],
                        "max_score": 20,
                        "weight": 0.3,
                        "rubric_levels": [{"label": "优秀", "description": "表现突出", "score": 18}],
                        "scoring_anchors": ["满分 20 分"],
                        "scoring_sources": ["满分 20 分"],
                    },
                    {"title": "创新性", "requirement": "创新点需与现有做法对比", "order": 5},
                ],
            },
            ensure_ascii=False,
        )

        draft = criteria_builder.draft_requirements(
            request_of(text=source, source_type="rubric_json", source_name="standard.json")
        )

        self.assertFalse(draft.model_assisted)
        self.assertEqual(self.complete.calls, [])
        self.assertEqual(draft.title, "结构化标准")
        self.assertEqual(draft.source_note, "来自用户文件")
        self.assertEqual(draft.aggregation_rule, "加权求和")
        self.assertEqual(draft.aggregation_rule_source, "加权求和")
        self.assertEqual(draft.source_text, source)
        first, second = draft.criteria
        self.assertEqual(first.id, "crit_keep")
        self.assertEqual((first.max_score, first.weight), (20, 0.3))
        self.assertEqual(first.rubric_levels[0].label, "优秀")
        self.assertEqual(first.scoring_anchors, ["满分 20 分"])
        self.assertEqual(first.scoring_sources, ["满分 20 分"])
        self.assertEqual((first.order, second.order), (0, 5))
        self.assertTrue(second.id.startswith("crit_"))
        self.assertEqual(second.required_evidence, [])

    def test_empty_scoring_lists_normalize_to_null(self) -> None:
        source = json.dumps(
            {
                "title": "无评分标准",
                "criteria": [
                    {
                        "title": "技术实现",
                        "requirement": "核心功能已实现",
                        "rubric_levels": [],
                        "scoring_anchors": [],
                        "scoring_sources": [],
                    }
                ],
            },
            ensure_ascii=False,
        )

        criterion = criteria_builder.draft_requirements(
            request_of(text=source, source_type="rubric_json")
        ).criteria[0]

        self.assertIsNone(criterion.rubric_levels)
        self.assertIsNone(criterion.scoring_anchors)
        self.assertIsNone(criterion.scoring_sources)

    def test_invalid_structured_json_is_rejected_without_llm(self) -> None:
        cases = {
            "not_json": "{不是 JSON",
            "array": "[]",
            "no_criteria": json.dumps({"title": "x"}, ensure_ascii=False),
            "duplicate_ids": json.dumps(
                {"title": "x", "criteria": [{"id": "same", "title": "a", "requirement": "b"}, {"id": "same", "title": "c", "requirement": "d"}]},
                ensure_ascii=False,
            ),
            "duplicate_orders": json.dumps(
                {
                    "title": "x",
                    "criteria": [
                        {"title": "a", "requirement": "b", "order": 0},
                        {"title": "c", "requirement": "d", "order": 0},
                    ],
                },
                ensure_ascii=False,
            ),
            "unknown_criterion_field": json.dumps(
                {"title": "x", "criteria": [{"title": "a", "requirement": "b", "points": 20}]},
                ensure_ascii=False,
            ),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(criteria_builder.DraftRejected):
                    criteria_builder.draft_requirements(request_of(text=text, source_type="rubric_json"))
        self.assertEqual(self.complete.calls, [])


class PublishTest(unittest.TestCase):
    """发布：校验 id/order、评分来源、不可覆盖旧 revision、保留来源。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        rubric_store.set_index({})

    def tearDown(self) -> None:
        rubric_store.reset_index()
        self._tmp.cleanup()

    def test_publish_returns_validated_sorted_rubric_with_provenance(self) -> None:
        payload = RubricPublish(
            title="发布标准",
            source_note="用户确认整理",
            source_type="markdown",
            source_name="requirements.md",
            source_text="# 要求\n- 可运行\n- 可复核\n聚合规则：加权求和。",
            aggregation_rule="加权求和",
            aggregation_rule_source="聚合规则：加权求和。",
            model_assisted=True,
            confirmed=True,
            criteria=[
                CriterionDraft(id="crit_2", order=2, title="创新性", requirement="有对比", required_evidence=[]),
                CriterionDraft(id="crit_1", order=1, title="技术实现", requirement="可运行", required_evidence=["说明"]),
            ],
        )

        rubric = rubric_store.publish(payload, self.directory)

        self.assertTrue(rubric.id.startswith("rubric_"))
        self.assertEqual(rubric.revision, 1)
        self.assertEqual([item.id for item in rubric.criteria], ["crit_1", "crit_2"])
        self.assertEqual(rubric.source_text, payload.source_text)
        self.assertEqual(rubric.source_type, "markdown")
        self.assertEqual(rubric.source_name, "requirements.md")
        self.assertEqual(rubric.aggregation_rule, "加权求和")
        self.assertEqual(rubric.aggregation_rule_source, "聚合规则：加权求和。")
        self.assertTrue(rubric.model_assisted)
        stored = rubric_store.get_rubric(rubric.id, 1)
        self.assertEqual(stored.model_dump(), rubric.model_dump())

    def test_publish_rejects_ungrounded_imported_scoring(self) -> None:
        criteria = [
            CriterionDraft(
                id="crit_a",
                order=0,
                title="技术实现",
                requirement="可运行",
                required_evidence=[],
                max_score=20,
                scoring_sources=["样本量 120 个。"],
            )
        ]
        payload = manual_publish(
            criteria=criteria, source_type="plain_text", source_text="样本量 120 个。"
        )

        with self.assertRaises(rubric_store.RubricRejected) as caught:
            rubric_store.publish(payload, self.directory)

        self.assertEqual(caught.exception.code, "invalid_rubric")
        self.assertTrue(any("max_score" in item for item in caught.exception.details))
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_publish_rejects_scoring_without_source_quotes(self) -> None:
        criteria = [
            CriterionDraft(
                id="crit_a", order=0, title="技术实现", requirement="可运行", required_evidence=[],
                max_score=20,
            )
        ]
        payload = manual_publish(criteria=criteria, source_type="markdown", source_text="满分 20 分。")

        with self.assertRaises(rubric_store.RubricRejected) as caught:
            rubric_store.publish(payload, self.directory)

        self.assertTrue(any("来源片段" in item for item in caught.exception.details))

    def test_publish_rejects_fabricated_level_description(self) -> None:
        criteria = [
            CriterionDraft(
                id="crit_a", order=0, title="技术实现", requirement="可运行", required_evidence=[],
                rubric_levels=[{"label": "优秀", "description": "表现突出", "score": None}],
                scoring_sources=["评级：优秀。"],
            )
        ]
        payload = manual_publish(criteria=criteria, source_type="plain_text", source_text="评级：优秀。")

        with self.assertRaises(rubric_store.RubricRejected) as caught:
            rubric_store.publish(payload, self.directory)

        self.assertTrue(any("description" in item for item in caught.exception.details))

    def test_manual_authored_scoring_is_accepted(self) -> None:
        criteria = [
            CriterionDraft(
                id="crit_a", order=0, title="技术实现", requirement="可运行", required_evidence=[],
                max_score=20, weight=0.5,
            )
        ]
        payload = manual_publish(criteria=criteria, source_type="manual", source_text="用户自撰评分规则")

        rubric = rubric_store.publish(payload, self.directory)

        self.assertEqual(rubric.criteria[0].max_score, 20)
        self.assertEqual(rubric.criteria[0].weight, 0.5)

    def test_scoring_sources_survive_publish(self) -> None:
        criteria = [
            CriterionDraft(
                id="crit_a", order=0, title="技术实现", requirement="可运行", required_evidence=[],
                max_score=20, scoring_sources=["满分 20 分。"],
            )
        ]
        payload = manual_publish(criteria=criteria, source_type="plain_text", source_text="满分 20 分。")

        rubric = rubric_store.publish(payload, self.directory)

        self.assertEqual(rubric.criteria[0].scoring_sources, ["满分 20 分。"])

    def test_publish_never_overwrites_existing_revision(self) -> None:
        first = rubric_store.publish(manual_publish(title="第一版"), self.directory)
        before = (self.directory / f"{first.id}.json").read_text(encoding="utf-8")

        second = rubric_store.publish(manual_publish(title="第二版"), self.directory)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 2)
        self.assertEqual((self.directory / f"{first.id}.json").read_text(encoding="utf-8"), before)
        reloaded = rubric_store.load_index(self.directory)
        self.assertEqual(reloaded[(first.id, 1)].title, "第一版")
        self.assertEqual(reloaded[(second.id, 1)].title, "第二版")

    def test_edited_draft_publishes_edits(self) -> None:
        drafts = [
            CriterionDraft(id="crit_a", order=0, title="原 A", requirement="原要求 A", required_evidence=[]),
            CriterionDraft(id="crit_b", order=1, title="原 B", requirement="原要求 B", required_evidence=[]),
        ]
        edited = [
            drafts[1].model_copy(update={"title": "改后 B", "order": 0}),
            drafts[0].model_copy(update={"order": 1}),
        ]
        payload = manual_publish(title="改后标准", criteria=edited)

        rubric = rubric_store.publish(payload, self.directory)

        self.assertEqual(rubric.title, "改后标准")
        self.assertEqual([item.id for item in rubric.criteria], ["crit_b", "crit_a"])
        self.assertEqual(rubric.criteria[0].title, "改后 B")

    def test_invalid_drafts_are_rejected_without_files(self) -> None:
        cases = {
            "duplicate_ids": [
                CriterionDraft(id="same", order=0, title="a", requirement="r", required_evidence=[]),
                CriterionDraft(id="same", order=1, title="b", requirement="r", required_evidence=[]),
            ],
            "duplicate_orders": [
                CriterionDraft(id="a", order=0, title="a", requirement="r", required_evidence=[]),
                CriterionDraft(id="b", order=0, title="b", requirement="r", required_evidence=[]),
            ],
            "blank_title": [
                CriterionDraft(id="a", order=0, title="   ", requirement="r", required_evidence=[]),
            ],
            "blank_requirement": [
                CriterionDraft(id="a", order=0, title="a", requirement="  ", required_evidence=[]),
            ],
            "blank_evidence": [
                CriterionDraft(id="a", order=0, title="a", requirement="r", required_evidence=["  "]),
            ],
        }
        for name, drafts in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(rubric_store.RubricRejected) as caught:
                    rubric_store.publish(manual_publish(criteria=drafts), self.directory)
                self.assertEqual(caught.exception.code, "invalid_rubric")
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_publish_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(ValidationError):
            RubricPublish.model_validate(
                {**manual_publish().model_dump(exclude={"confirmed"})}
            )


class CriteriaBuilderRouteTest(unittest.TestCase):
    """API 直调层：draft/publish 路由与 400/502 映射。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmp.name)
        self._original_dir = rubric_store.DEFAULT_RUBRIC_DIR
        self._original_complete = llm.complete
        self._original_settings = llm.load_settings
        rubric_store.DEFAULT_RUBRIC_DIR = self.directory
        rubric_store.set_index({})

    def tearDown(self) -> None:
        rubric_store.DEFAULT_RUBRIC_DIR = self._original_dir
        rubric_store.reset_index()
        llm.complete = self._original_complete
        llm.load_settings = self._original_settings
        self._tmp.cleanup()

    def test_draft_route_returns_draft(self) -> None:
        llm.load_settings = lambda: llm.LlmSettings("http://stub/v1", "k", "m", 1.0)
        self.complete = StubComplete([reply_of(criteria=[criterion_payload()])])
        llm.complete = self.complete

        draft = main.draft_rubric(request_of())

        self.assertEqual(len(draft.criteria), 1)
        self.assertEqual(draft.source_text, SOURCE_TEXT)

    def test_publish_route_writes_new_immutable_rubric(self) -> None:
        first = main.publish_rubric(manual_publish(title="路由标准"))
        second = main.publish_rubric(manual_publish(title="路由标准"))

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 2)
        self.assertEqual(rubric_store.get_rubric(first.id, 1).title, "路由标准")

    def test_rejected_drafts_map_to_400(self) -> None:
        import asyncio

        draft_response = asyncio.run(
            main.draft_rejected(None, criteria_builder.DraftRejected("坏 JSON", ["detail"]))
        )
        self.assertEqual(draft_response.status_code, 400)
        body = json.loads(draft_response.body)
        self.assertEqual(body["code"], "invalid_rubric_source")
        self.assertEqual(body["details"], ["detail"])

        publish_response = asyncio.run(
            main.rubric_rejected(None, rubric_store.RubricRejected("校验失败", ["crit: title"]))
        )
        self.assertEqual(publish_response.status_code, 400)
        body = json.loads(publish_response.body)
        self.assertEqual(body["code"], "invalid_rubric")
        self.assertEqual(body["details"], ["crit: title"])


if __name__ == "__main__":
    unittest.main()
