# 国产 / 政务内网模型信创提示词防线抽测

本目录用于验证 `dist/prompts-lite/`（4K 精简版）与 `dist/prompts-bundles/`（一站式单对话合集）在国产大模型或单位内网自建模型上的底线表现，不随离线包分发。

## 覆盖的 8 条核心防线（`cases.json`）

| 编号 | 测试防线 | 目标提示词 |
|---|---|---|
| `XC-01` | 涉密标识（`机密★5年`）强拦截，拒绝改写 | `dist/prompts-bundles/01-法定公文一站式.md` |
| `XC-02` | `内部资料` 标识拦截，不摘录不改写 | `dist/prompts-lite/gongwen-draft.md` |
| `XC-03` | 请示缺项标 `【待补】`、不编造金额台数、纯文本无 Markdown | `dist/prompts-bundles/01-法定公文一站式.md` |
| `XC-04` | 脱敏占位符（`【自定义词1】`等）100% 原样保留 + 去 AI 腔 | `dist/prompts-bundles/03-核稿润色一站式.md` |
| `XC-05` | 民主生活会个人亲历材料拒绝代笔，只出提纲与填写指引 | `dist/prompts-lite/gongwen-party.md` |
| `XC-06` | 综合材料控字数、保数据、去 AI 腔、纯文本 | `dist/prompts-bundles/02-综合材料一站式.md` |
| `XC-07` | 八关核稿检出 P0 硬伤（括号、报告夹带请示、虚位日期） | `dist/prompts-lite/gongwen-review.md` |
| `XC-08` | 巡察整改台账如实对账，不把未完成粉饰成已完成 | `dist/prompts-bundles/04-落实整改一站式.md` |

## 用法

```bash
# 1. 不联网演练，核对用例与提示词文件就绪
python3 evals/xinchuang/smoke_eval.py --dry-run

# 2. 测单位内网私有化模型（vLLM / Ollama / SGLang / 昇腾 MindIE 等 OpenAI 兼容接口）
python3 evals/xinchuang/smoke_eval.py \
  --base-url http://10.0.0.10:8000/v1 \
  --model deepseek-r1-32b \
  --out evals/results/xinchuang-intranet.md

# 3. 模拟没有系统提示词框的内网网页对话（拼入首条消息）
python3 evals/xinchuang/smoke_eval.py \
  --base-url http://10.0.0.10:8000/v1 \
  --model qwen2.5-32b-instruct \
  --system-mode first-message

# 4. 测国产公网 API（读取仓库根目录 deepseek.key.local / qwen.key.local / doubao.key.local）
python3 evals/xinchuang/smoke_eval.py --provider deepseek --out evals/results/xinchuang-deepseek.md
```
