Tanze（探赜）论文初稿
====================

正文：main.tex
参考文献：references.bib
编译结果：build/main.pdf
论断与证据索引：evidence-notes.txt（英文研究记录）

范围与结构
----------
本稿采用英文、通用双栏 article 格式，仅撰写用户要求的四个部分及引用文献：

Abstract
1. Introduction
2. Background
   2.1 Consensus implementations
   2.2 LLMs for bug discovery
   2.3 Investigation challenges
3. Tanze Design
   3.1 Investigation workflow
   3.2 Forming questions
   3.3 Building executable evidence
   3.4 Revision and continuation

第 1 节按“CFT 的重要性与实现难点—LLM 调查的证据要求—解释修订与继续调查的
核心挑战—Tanze 方法与机制—贡献及效果占位”展开，不详细复盘具体缺陷，也不
逐项综述相关系统。具体案例保留在 Design，详细比较留给后续独立 Related Work。
第 2 节先介绍共识、复制状态机、安全性与活性，再介绍 LLM 结合源码、测试和
模型检查发现缺陷的工作方式，最后引出调查所需连接的前提、前史和观察。
第 3 节围绕选题、取证、修正和继续调查展开，HashiCorp 恢复案例用于解释如何
形成问题、补齐试验前史和观察实际后果；三个语义对象服务于这个过程。
图 1 展示源码推理与执行证据如何汇入同一调查，图 2 展示案例前史；图均为可编辑
的 TikZ 矢量图。表 1 说明五类支持机制各自承载的实现责任。
正文不以具体 Git 版本或归档说明引入案例；精确版本和回执定位保留在证据索引中。

暂定名称集中于 main.tex 的 \newcommand{\sys}{Tanze}，正文、标题和 PDF
元数据均使用这个宏。当前标题是：
Tanze: Evidence-Guided Investigation of CFT Consensus Implementations

写作依据
--------
使用 nature-writing 的方法论文、manuscript、abstract/intro/method、zh-to-en、
generic 配置；先从当前实现与案例确立设计论点，再写引言与摘要：
https://github.com/Yuan1z0825/nature-skills/blob/main/skills/nature-writing/SKILL.md

同时遵循先前指定的避免防御性论述要求：
https://github.com/Kiterlin/anti-defensive-writing

SYSSPEC、Specula、Agora 用于参考“问题—关键观察—机制—证据”的论述组织。
Introduction 仅以简短引用说明已有能力，具体系统比较留到 Related Work。
主张限于已实现的机制与已有案例事实；不把归档中的主张数写成独立验证的缺陷数，
不添加尚未完成的比较实验。

设计描述以 audit-products-v80 为依据，初稿写作时工作树包含未提交修改；
详细写作依据见 evidence-notes.txt。正文案例来自两次 audit-products-v79 历史运行。
稿件写作没有执行新的目标实验或改写归档。
作者暂列 Yuxin Du，单位 Shanghai Jiao Tong University。
目前未指定投稿会议，因此采用通用双栏格式。
Evaluation、独立 Related Work、Discussion 和 Conclusion 不在本次撰写范围。
后续完整论文仍需安排比较实验与消融来支持效果和成本方面的结论。
摘要按“共识的重要性—LLM 审计难点—Tanze 方案—效果”组织，效果部分暂保留
可见占位 [Evaluation results to be added.]，待评估完成后补写。
Introduction 末尾另留效果占位，待补充评估实现、经验证的发现、代表性案例以及
支持设计的对比或消融结果。

编译
----
使用本机已有 TeX Live / MiKTeX 与 latexmk 时，在 paper 目录执行：

    make

使用 Tectonic 时：

    make tectonic

本次使用临时目录中的官方 Tectonic 0.15.0 编译，未全局安装软件：

    XDG_CACHE_HOME=/tmp/tanze-tex-cache make tectonic TECTONIC=/tmp/tanze-tools/tectonic

首次编译需要获取排版包；缓存齐备后可离线编译：

    XDG_CACHE_HOME=/tmp/tanze-tex-cache /tmp/tanze-tools/tectonic --only-cached --untrusted --reruns 2 --keep-logs --keep-intermediates --outdir build main.tex

build/ 为可再生编译产物，不纳入 Git 追踪。make clean 只清理辅助文件，保留 PDF。
