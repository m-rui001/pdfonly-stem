# 非编码RNA调控网络：数据资源与分析

> Non-coding RNA regulatory networks, 2019, https://doi.org/10.1016/j.bbagrm.2019.194417

非编码RNA（ncRNA）虽不编码蛋白质，却在细胞生理和功能调控中发挥关键作用，其异常表达与多种侵袭性疾病相关。本文概述了收集和注释ncRNA调控相互作用的公共数据库，讨论了数据整合中的未解决问题，并回顾了构建和分析网络的现有资源，强调网络生物学方法可为基因调控与功能失调机制提供新见解。

## 转录调控中的非编码RNA

调控网络由分子因子与基因相互作用的复杂网络构成，除转录因子外，ncRNA也广泛参与。microRNA约22个核苷酸，通过RISC复合体结合mRNA的3'UTR种子序列，引导切割或抑制翻译。miRBase收录约1915个人类microRNA前体，其中至少725个为高置信度鉴定。靶标预测主要基于种子互补，常用工具包括TargetScan（考虑序列保守性和位点可及性）、PicTar、miRanda、RNAhybrid（最小自由能）、RNA22（模式发现）和机器学习方法。lncRNA定义为长度超过200核苷酸且不编码蛋白质的转录本，但该定义模糊，部分已知lncRNA（如Xist、H19）含潜在ORF，可能为双功能转录物。lncRNA可通过结合组蛋白修饰酶（如Hotair）、反义配对或microRNA海绵效应发挥作用；免疫基因启动型lncRNA（IPL）能招募WDR5-MLL1至靶启动子，以顺式方式调控免疫基因。circRNA由反向剪接形成，常含外显子、内含子或基因间区域，circBase等数据库注释了数千个circRNA，但需经RNase R处理排除假阳性。增强子RNA（eRNA）与激活的组蛋白标记相关，可结合CBP并刺激其组蛋白乙酰转移酶活性。以p53网络为例：p53激活miR34a、miR15、miR200、miR145、miR107等microRNA，并激活lincRNA-p21和lincMkln1，后者分别与hnRNP K/DNMT1和PRC2复合体作用以抑制靶基因；p53本身也受miR125b、miR504等下调，miR145还调节MDM2，构成高度互联的调控网络。

## 构建ncRNA调控网络的数据来源

调控网络可建模为图，节点为RNA、蛋白质和基因，边表示物理结合或因果调节。数据分为预测和实验验证两类。预测网络依赖序列互补，整合平台如miRecords、starBase、miRWalk可汇总多个算法的预测结果。不同算法差异大，常用3-4个算法交集以降低假阳性，但可能漏掉真实靶标。对miR-17的实例：starBase以TargetScan和“very high stringency”得到超过700个相互作用（646个mRNAs）；四个算法（TargetScan、picTar、PITA、miRanda）交集降至349个mRNAs，与39个已知true positives比较分别有13和12个命中；若将其中一个替换为RNA22，则仅预测40个靶标，其中只有3个true positive，说明需以已知例证校准预测方法。RNAcentral为ncRNA提供统一标识符。circRNA预测工具包括CircInteractome（结合CLIP数据和TargetScan）和CircNet（基于种子序列）。实验验证方法包括荧光素酶报告基因、凝胶迁移率变动分析（EMSA）、RNA免疫沉淀，以及高通量的CLIP、HITS-CLIP、PAR-CLIP、CLASH和ChIA-PET。数据库方面，starBase注释了来自700多CLIP实验的RNA-蛋白相互作用；RAID整合18个资源，包含超过300万RNA-RNA相互作用，但大多为预测或弱证据，每项带来源和可靠性评分；RAIN将ncRNA相互作用整合到STRING；LnChrom和LIVE专收lncRNA数据；SignaLink2、SIGNOR和Reactome提供因果通路数据。GO联盟已开始注释实验验证的microRNA相互作用，采用“mRNA binding”等术语，通过EBI-GOA-miRNA文件提供。IntAct数据库扩展至核酸实体，包含超过42000个涉及核酸的相互作用，采用PSI-MI-XML 2.5格式记录分子特征。然而，不同资源使用不同基因/转录本标识符，映射是数据整合的必要步骤。

## 调控网络的分析方法

igraph和Cytoscape等工具用于构建和可视化网络，酵母RNA相互作用组分析显示其为无标度网络，与蛋白质互作网络相似。网络表示方式有活动流图（活动间刺激/抑制边）、过程描述（双向图）和实体关系图（非对称调节关系）。网络比对方法如PathBLAST可寻找保守通路，全局比对、局部比对和网络查询各有应用。网络模体研究识别出前馈回路（FFL）和bi-fan等重复模式，人类转录网络中发现2377个microRNA介导的FFL。NetMatch和NetMatchStar Cytoscape插件支持用户绘制模体进行搜索。GO术语已可注释microRNA和少量lncRNA，支持对调控网络进行功能富集分析，如与miRNA靶基因相关的生物学过程（血管生成、白细胞黏附）等。

## 结论与挑战

ncRNA在基因调控中至关重要，但大多数lncRNA功能未知，且估计的丰度依赖于转录证据和缺乏编码潜力，方法差异导致估计不同。当前调控网络存在三个弱点：标识符不统一（RNAcentral虽已建立，但microRNA仍多用miRBase，lncRNA多用基因组位置；FANTOM 5项目通过CAGE提供转录组图谱），GO术语覆盖不足，以及缺乏统一标准。大多数相互作用来自大规模预测或文本挖掘，亟需人工策展的金标准数据集。尽管有这些挑战，整合研究已为疾病机制和治疗靶标提供新见解。
