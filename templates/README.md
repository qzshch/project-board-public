# 可复制模板

MANUAL.md给出完整顺序。JSON文件默认是治理动作payload（task-create.json例外，它是完整events请求）。复制后填写项目真实值，再由客户端prepare-governance/prepare-shared冻结请求版本与ID。0组成的提交/SHA及尖括号路径均是**待填写占位**，不能当作实测证据。默认inputs_known=false、资产private/shareable=false，防止示例直接冒充已核定范围或可共享内容。

顺序：project-init→knowledge/member/milestone→contract-freeze/asset-private→task-create/package→agent-brief→claim/submit→rework与重提→delivery-manifest→se-handoff→archive-checklist。接口升级用contract-change；资产发布/固定消费用asset-publish/asset-consume。示例项目ID不能替代真实服务授权。
