# 国产信创环境（银河麒麟 / 统信 UOS + WPS）与 OFD 核验

适用：单位电脑是国产操作系统，用 WPS 政务版、专业版或永中 Office，没有 Python 或不能装依赖。参数仍以 `references/_shared/rules/gbt9704.md` 为准，本文只补环境差异。

## 一、字体安装（Linux）

单用户复制到 `~/.local/share/fonts/`，全用户复制到 `/usr/share/fonts/custom/`（需 sudo），也可在系统「字体管理器」导入；随后运行 `fc-cache -f` 刷新缓存。缺字体不得用替代字体顶替。

本单位制度明文规定用方正 GBK 字体族的，核对和排版时加 `--unit-fonts preset:fangzheng-gbk`（可用预设：fangzheng-gbk、fangzheng-gbk-stdsong）。没装同样报「字体缺失」，不回退。

没有 `fc-list` 的精简系统，`gw_fonts.py` 会递归扫描 `/usr/share/fonts`、`/usr/local/share/fonts`、`~/.local/share/fonts` 及 WPS、方正字体目录。

## 二、WPS 菜单对照

1. 页边距与网格：页面布局 → 页边距 → 自定义页边距；同一弹窗切到「文档网格」，选「指定行和字符网格」，每行 28 字、每页 22 行。部分政务版自带公文排版功能，仍按 `references/manual-setup.md` 第二至四部分核对实测边距和行距（固定值 28.9 磅）。
2. 奇偶页页码：页面设置 → 版式，勾选「奇偶页不同」；插入 → 页码，再在页脚数字两侧手工补一字线（U+2014），四号宋体，奇数页右缩进 1 字符、偶数页左缩进 1 字符。
3. 免 Python 排版：`assets/wps_gongwen_macro.js` 是 WPS 的 JS 宏，套用页边距、文档网格、正文与各级标题字体、行距。宏是否可用取决于 WPS 版本和单位安全策略，信息中心可能禁用宏；禁用宏时优先直接打开 `xinchuang/templates/` 里的 5 套 GB/T 9704 空白 `.docx` 模板（白头、红头、纪要、签报、综合材料）粘贴正文，或按 `references/manual-setup.md` 手动设置。有 Python 但装不上 `python-docx`/`lxml`（如龙芯机器）时，可直接用 `xinchuang/local_toolbox.py` 按钮⑦或命令行 `python3 xinchuang/lite_docx.py 正文.txt -o 成稿.docx` 走纯标准库轻量排版。

## 三、导出 OFD 后的核验清单

OA 流转、电子签章和归档常要求 OFD（GB/T 33190）。用 WPS「导出为 OFD」或永中转换后，用数科、福昕或 WPS 的 OFD 阅读器逐项核对；有 Python 时先跑 `python scripts/ofd_check.py 成稿.ofd` 做结构体检。

1. 字体：文件属性里确认标准字体（或单位规定的方正 GBK 字体）已写入，没有回退成思源、文泉驿、DejaVu 等默认字体。
2. 折行与页数：对照原 docx 逐页看是否仍是每页 22 行、每行 28 字；重点看末页落款是否被挤成孤页，版记是否跨页。
3. 红头与红线：发文机关标志为红色，红色分隔线完整居中，无断线、偏移。
4. 印章留白：需加盖电子印章的，成文日期右空四字，印章位置不遮挡末行正文；印章尺寸以本单位印章为准（公章一般约 42 mm）。
5. 附件与页码：附件另面编排时页码与正文连续；版记前有空白页的，空白页和版记页不编页码。

以上以打印或阅读器实际效果为准，本工具不能替代电子签章系统的校验。
