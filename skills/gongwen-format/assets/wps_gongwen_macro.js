/*
 * WPS 文字「JS 宏」：一键套用 GB/T 9704-2012 页面与正文格式。零 Python 依赖，只改当前文档的格式，
 * 不改文字、不联网、不读写其他文件。
 *
 * 用法：WPS 文字 → 开发工具 → 「WPS 宏编辑器」→ 新建模块，粘贴本文件，运行 GongwenFormat。
 * 套用：A4，边距上 37、下 35、左 28、右 26 mm；每页 22 行、每行 28 字；
 *       正文仿宋_GB2312 三号，固定行距 28.9 磅，首行缩进 2 字符；
 *       首个非空段落按标题处理：方正小标宋简体二号居中；
 *       “一、”开头设黑体，“（一）”开头设楷体_GB2312（与正文同段时只设到第一个句号）。
 * 不做：红头、版记、页码、附件说明、署名和成文日期缩进、表格；这些按 references/manual-setup.md 手动设置，
 *       或直接使用 xinchuang/templates/ 下的 5 套空白公文模板。
 *       红头文件、简报的标题位置不同，本宏不适用。
 * 前提：字体已装（见 references/xinchuang.md）；缺字体时 WPS 会静默替换显示，不是正式效果。
 *       已有手工格式的段落，先全选清除格式再运行。
 * 兼容：已针对 Linux WPS 政务版/专业版补齐样式名（-1 / 正文 / Normal）、段落格式对象和首行缩进回退；
 *       某一步报错会被跳过并在结尾列出，按手动清单补设。
 */
var FAILED = [];

function mm(v) { return v * 72 / 25.4; }

function step(name, fn) {
  try { fn(); } catch (e) { FAILED.push(name); }
}

function notify(msg) {
  try { Application.Alert(msg); } catch (e) { try { alert(msg); } catch (e2) {} }
}

function setFont(font, name, size) {
  font.Name = name;
  try { font.NameFarEast = name; } catch (e) {}
  try { font.NameAscii = name; } catch (e) {}
  try { font.NameOther = name; } catch (e) {}
  font.Size = size;
  try { font.Bold = false; } catch (e) {}
}

function getNormalStyle(doc) {
  var keys = [-1, '正文', 'Normal'];
  for (var i = 0; i < keys.length; i++) {
    try {
      var st = doc.Styles.Item(keys[i]);
      if (st) return st;
    } catch (e) {}
  }
  return null;
}

function getParaFormat(p) {
  if (p.Format) return p.Format;
  if (p.ParagraphFormat) return p.ParagraphFormat;
  return null;
}

function setFirstIndentChars(pf, chars) {
  try {
    pf.CharacterUnitFirstLineIndent = chars;
  } catch (e) {
    pf.FirstLineIndent = chars * 16;  // 三号 16 磅/字兜底
  }
}

// 标题与正文同段时，只取到第一个句号为止
function headRange(doc, p, text) {
  var cut = text.indexOf('。');
  if (cut >= 0 && cut < text.length - 1) {
    return doc.Range(p.Range.Start, p.Range.Start + cut + 1);
  }
  return p.Range;
}

function GongwenFormat() {
  var doc = Application.ActiveDocument;
  if (!doc) { notify('没有打开的文档'); return; }
  FAILED = [];

  step('页面设置', function () {
    var ps = doc.PageSetup;
    ps.PageWidth = mm(210);
    ps.PageHeight = mm(297);
    ps.TopMargin = mm(37);
    ps.BottomMargin = mm(35);
    ps.LeftMargin = mm(28);
    ps.RightMargin = mm(26);
    try { ps.OddAndEvenPagesHeaderFooter = true; } catch (e) {}
  });

  step('文档网格', function () {
    var ps = doc.PageSetup;
    ps.LayoutMode = 3;  // 指定行和字符网格
    ps.CharsLine = 28;
    ps.LinesPage = 22;
  });

  step('正文样式', function () {
    var st = getNormalStyle(doc);
    if (!st) throw new Error('未找到正文样式');
    setFont(st.Font, '仿宋_GB2312', 16);
    var pf = st.ParagraphFormat;
    pf.Alignment = 3;
    pf.LineSpacingRule = 4;  // 固定值
    pf.LineSpacing = 28.9;
    pf.SpaceBefore = 0;
    pf.SpaceAfter = 0;
    setFirstIndentChars(pf, 2);
  });

  step('标题与层次标题', function () {
    var titled = false;
    var n = doc.Paragraphs.Count;
    for (var i = 1; i <= n; i++) {
      var p = doc.Paragraphs.Item(i);
      var text = p.Range.Text.replace(/[\r\n\u0007]+$/, '');
      if (text.replace(/\s/g, '') === '') continue;
      var inTable = false;
      try { inTable = p.Range.Information(12); } catch (e) {}
      if (inTable) continue;
      var pf = getParaFormat(p);
      var isH1 = /^[一二三四五六七八九十]+、/.test(text);
      var isH2 = /^（[一二三四五六七八九十]+）/.test(text);
      if (!titled) {
        titled = true;
        if (!isH1 && !isH2) {
          setFont(p.Range.Font, '方正小标宋简体', 22);
          if (pf) {
            pf.Alignment = 1;
            setFirstIndentChars(pf, 0);
          }
          continue;
        }
      }
      // 先按正文基线设字，防止原稿手工字体残留，再覆盖一级/二级标题字体
      setFont(p.Range.Font, '仿宋_GB2312', 16);
      if (isH1) {
        setFont(headRange(doc, p, text).Font, '黑体', 16);
      } else if (isH2) {
        setFont(headRange(doc, p, text).Font, '楷体_GB2312', 16);
      }
    }
  });

  if (FAILED.length) {
    notify('已套用，但以下步骤失败，请按手动清单补设：' + FAILED.join('、'));
  } else {
    notify('已套用 GB/T 9704 页面与正文格式。页码、红头、版记、署名日期请按手动清单设置，并打印核对。');
  }
}
