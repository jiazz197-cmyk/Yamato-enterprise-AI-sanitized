# U8 BOM + Inventory 查询表结构说明

## 概述

U8 BOM + Inventory 递归查询用于展开 BOM 结构并关联库存成本信息。本文档说明查询涉及的数据库表及其关系。

---

## 使用的表

### 主要查询表

| 表名 | 别名 | 用途 |
|------|------|------|
| `v_bas_part` | `vp` | 物料主数据视图，获取 PartId 和 InvCode 的映射关系 |
| `bom_parent` | `bp` | BOM 父件关系表，关联父件与 BOM |
| `bom_opcomponent` | `oc` | BOM 子件明细表，包含子件、用量、排序等信息 |
| `bom_bom` | `b` | BOM 主表，用于筛选状态为生效的 BOM（Status=3） |
| `Inventory` | `ic` | 存货档案表，获取成本价、名称、规格、仓库等信息 |

### 诊断查询表

| 表名 | 用途 |
|------|------|
| `v_bas_part` | 诊断用，检查 InvCode/PartId 是否命中（当根节点无子件时记录日志） |

---

## 表关系图

```
┌─────────────────┐
│  v_bas_part     │
│    (parent)     │
│  PartId         │
│  InvCode        │
└────────┬────────┘
         │ PartId
         ▼
┌─────────────────┐       ┌─────────────────┐
│   bom_parent    │       │    bom_bom      │
│   ParentId      │──────►│     BomId       │
│   BomId         │       │   Status=3      │ (只取生效的BOM)
└────────┬────────┘       └─────────────────┘
         │ BomId
         ▼
┌─────────────────┐
│bom_opcomponent  │
│   BomId         │
│   ComponentId   │──────► PartId (子件)
│   SortSeq       │
│   BaseQtyN      │       用量分子
│   BaseQtyD      │       用量分母
│   CompScrap     │       损耗率
└─────────────────┘
         │
         │ ComponentId = PartId
         ▼
┌─────────────────┐       ┌─────────────────┐
│  v_bas_part     │       │   Inventory     │
│    (child)      │──────►│   cInvCode      │
│   PartId        │       │   cInvName      │ 名称
│   PartInvCode   │       │   iInvSprice    │ 标准价
└─────────────────┘       │   iInvNcost     │ 成本价
                          │   cInvStd       │ 规格型号
                          │   cInvDepCode   │ 部门
                          │   cDefWareHouse │ 默认仓库
                          └─────────────────┘
```

---

## SQL 查询逻辑

### 核心查询语句

```sql
-- 物料编码映射 CTE
WITH PartMap AS (
    SELECT
        vp.PartId,
        COALESCE(
            NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
            NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
        ) AS PartInvCode
    FROM v_bas_part vp
)

-- 主查询
SELECT
    parent.PartInvCode AS ParentInvCode,    -- 父件编码
    child.PartInvCode AS ChildInvCode,      -- 子件编码
    oc.BomId,                                -- BOM ID
    oc.SortSeq,                              -- 排序号
    oc.BaseQtyN,                             -- 用量分子
    oc.BaseQtyD,                             -- 用量分母
    oc.CompScrap,                            -- 损耗率
    CAST(1.0 * oc.BaseQtyN / NULLIF(oc.BaseQtyD, 0) AS DECIMAL(38,12)) AS QtyPer,  -- 单件用量
    ic.cInvName,                             -- 存货名称
    ic.iInvSprice,                           -- 标准价
    ic.iInvNcost,                            -- 成本价
    ic.cInvStd,                              -- 规格型号
    ic.cInvDepCode,                          -- 部门编码
    ic.cDefWareHouse,                        -- 默认仓库
    child.PartId AS ChildPartId              -- 子件 PartId
FROM PartMap parent
JOIN bom_parent bp ON bp.ParentId = parent.PartId
JOIN bom_opcomponent oc ON oc.BomId = bp.BomId
JOIN bom_bom b ON b.BomId = bp.BomId AND b.Status = 3  -- 只取生效状态
JOIN PartMap child ON child.PartId = oc.ComponentId
LEFT JOIN Inventory ic ON ic.cInvCode = child.PartInvCode
WHERE parent.PartInvCode = N'{parent_code}'
ORDER BY oc.SortSeq, child.PartInvCode
```

---

## 字段说明

### bom_bom 表

| 字段 | 说明 |
|------|------|
| `BomId` | BOM 主键 ID |
| `Status` | BOM 状态（3 = 生效） |

### bom_parent 表

| 字段 | 说明 |
|------|------|
| `BomId` | BOM ID |
| `ParentId` | 父件 PartId |

### bom_opcomponent 表

| 字段 | 说明 |
|------|------|
| `BomId` | BOM ID |
| `ComponentId` | 子件 PartId |
| `SortSeq` | 排序号 |
| `BaseQtyN` | 基本用量分子 |
| `BaseQtyD` | 基本用量分母 |
| `CompScrap` | 损耗率 |

### v_bas_part 视图

| 字段 | 说明 |
|------|------|
| `PartId` | 物料内部 ID（主键） |
| `InvCode` | 物料编码 |
| `cInvCode` | 物料编码（备用字段） |

### Inventory 表

| 字段 | 说明 |
|------|------|
| `cInvCode` | 存货编码 |
| `cInvName` | 存货名称 |
| `iInvSprice` | 标准价 |
| `iInvNcost` | 成本价 |
| `cInvStd` | 规格型号 |
| `cInvDepCode` | 部门编码 |
| `cDefWareHouse` | 默认仓库 |

---

## 关键业务逻辑

### 1. BOM 状态筛选

只查询 `Status = 3` 的 BOM，即只展开生效状态的 BOM。

### 2. 物料编码获取

```sql
COALESCE(
    NULLIF(LTRIM(RTRIM(vp.InvCode)), ''),
    NULLIF(LTRIM(RTRIM(vp.cInvCode)), '')
)
```

优先使用 `InvCode`，如果为空则使用 `cInvCode`。

### 3. 用量计算

```sql
QtyPer = BaseQtyN / BaseQtyD
```

单件用量 = 分子 / 分母

### 4. 递归展开

- 从根节点（parent_inv_code）开始
- 递归查询每个子件的 BOM
- 使用 `visited_part_ids` 防止循环引用
- 支持 `max_depth` 限制递归深度

---

## 代码位置

- 查询实现：`app/integrations/sqlserver/u8_bom.py`
- API 路由：`app/api/v1/sqlserver_queries.py`
- UseCase：`app/usecases/sqlserver_queries/run_queries.py`
