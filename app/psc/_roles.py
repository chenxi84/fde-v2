# psc 组角色声明（下沉：本组的智能体角色，平台扫描装配进 agent_roles）
ROLES = [
    {"type": "sales", "label": "销售/需求专家",
     "apps": ["psc/md_customer", "psc/md_monthly_version", "psc/attainment",
              "psc/sales_forecast", "psc/sales_history", "psc/strategy_fitting"]},
    {"type": "planning", "label": "计划/排产专家",
     "apps": ["psc/md_project", "psc/md_project_part", "psc/demand",
              "psc/master_plan", "psc/demand_pool"]},
    {"type": "inventory", "label": "物料/库存专家",
     "apps": ["psc/md_material", "psc/md_breakpoint", "psc/md_part_replace",
              "psc/inventory_strategy", "psc/inventory_projection"]},
    {"type": "delivery", "label": "交付/出库专家",
     "apps": ["psc/outbound_plan"]},
]
