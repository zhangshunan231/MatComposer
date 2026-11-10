# MatComposer

**面向程序化材质图创作的结构—语义检索与迭代探索系统**

[English](README.md) · [论文](https://doi.org/10.1145/3830398.3830601) · [安装指南](docs/INSTALLATION.md) · [材质说明](docs/MATERIALS.md)

论文：*MatComposer: Structural-Semantic Retrieval and Iterative Exploration for Procedural Material Graph Authoring*

作者：Shunan Zhang、Yi Xiao、Guangpeng Wei、Yang Zhou、Zeyu Liu

会议：UIST 2026，Proceedings of the 39th Annual ACM Symposium on User Interface Software and Technology

MatComposer 是一个 Blender 插件，通过语义描述和材质节点图的结构信息检索材质，并支持 Base / Overlay / Detail 槽位组合、程序化遮罩和迭代探索。可联合探索语义与结构，也可锁定其中一个空间。

## 材质与版权

**由于版权原因，目前仅上传本仓库中包含的部分材质及遮罩资源，暂不提供论文实验使用的完整材质库。** 使用检索与组合功能时，请自行准备具有合法使用权限的材质库。当前资源子集不足以复现论文完整的材质覆盖与实验结果。

代码采用 **GPL-3.0-only** 许可证。材质、遮罩、预览图及第三方资源元数据不自动适用代码许可证，其版权和许可条件仍归原权利人所有。请查看[资源清单与配置方法](docs/MATERIALS.md)和[第三方声明](THIRD_PARTY_NOTICES.md)。

## 安装与使用

1. 推荐按照文档使用 Blender 4.4.x；插件声明的最低版本为 4.0，其余版本尚未在本次整理中验证。
2. 克隆仓库，在根目录运行 `python scripts/package_addon.py`，生成 `dist/MatComposer-1.0.0.zip`。仓库保持私有期间，克隆需要访问权限。
3. 在 Blender 的 **编辑 → 偏好设置 → 插件 → 从磁盘安装** 中选择 ZIP，启用 MatComposer。
4. 在 **偏好设置 → 文件路径 → 资产库** 中添加自己的材质库。材质需要标记为资产，并归入 `MyMaterial` 或其子目录；目录配置见[材质说明](docs/MATERIALS.md)。
5. 选择具有活动材质的网格对象，进入 **着色器编辑器**，按 **N** 打开 MatComposer 面板。
6. 填入自己的 DashScope API Key，扫描资产库，输入描述，依次执行 **Semantic Init → Search Slots**。
7. 选择候选材质及遮罩，使用 **Explore** 迭代，再通过 **Exploration & Evolution** 面板组装材质。

交互插件使用 Blender 自带的 Python，无需额外安装 pip 包。语义初始化需要联网调用 DashScope；可选的 CLIP、GNN 预处理及绘图脚本依赖见[脚本指南](docs/SCRIPTS.md)。API Key 不随插件分发，也不会由该属性保存到 `.blend` 文件。

详细文档和 BibTeX 请查看 [English README](README.md) 与 [citation.bib](citation.bib)。
