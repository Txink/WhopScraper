# 多日重叠 Tab 日历延迟弹出 — 设计说明

**日期**：2026-05-22
**范围**：股票详情面板（DetailPane）顶部的 tab 切换交互

## 背景

当前在 `frontend/src/components/Positions/DetailPane.tsx:170-182` 中，「多日重叠」（overlay）tab 的点击处理对 inactive → active 这一步做了特殊处理：切换视图的同时会自动把日历 popover 弹出来。原始动机记录在 176-177 行的注释里：让用户不用点两次就能开始选日期。

实际使用中，这个自动弹出让从其他 tab 切到 overlay 时多了一个需要立刻处理（关掉或选日期）的浮层，干扰了"只是想切个 tab 看一眼"的路径。

## 目标

把 overlay tab 的点击行为对齐到其他 tab：切 tab 是切 tab，开日历是开日历，分两次点击完成。

## 改造前后对比

| 触发场景 | 改前 | 改后 |
|---|---|---|
| 当前在其他 tab，点击「多日重叠」 | 切到 overlay 视图 + 自动弹出日历 | 切到 overlay 视图，日历保持关闭 |
| 已在 overlay tab，日历关闭，点击 tab | 弹出日历（toggle） | 弹出日历（toggle，不变） |
| 已在 overlay tab，日历打开，点击 tab | 关闭日历（toggle） | 关闭日历（toggle，不变） |

第二、第三行的「toggle」行为由原 181 行的 `setOpenPopover((cur) => (cur === t.id ? null : t.id))` 已经覆盖，本次不动。

## 代码改动

文件：`frontend/src/components/Positions/DetailPane.tsx`

第 176-178 行：
```js
// 改前
// overlay tab opens its calendar on activation too so the
// user doesn't have to click twice to start selecting days.
setOpenPopover(t.id === "overlay" ? "overlay" : null);

// 改后
setOpenPopover(null);
```

注释（176-177 行）一并删掉，因为它描述的就是被去掉的那段行为。

## 已知取舍

用户第一次进入 overlay tab 且 `overlayDates` 为空时会看到空图，需要再点一次 tab 弹出日历选日期。可以接受 —— 这正是改造的初衷：把"切 tab"和"选日期"这两个动作分开。

## 不在本次范围

- minute / multiday / dayK 三个 tab 的点击行为
- CalendarPopover 组件内部的日历逻辑
- DetailChartOverlay 的渲染逻辑
- 空 `overlayDates` 时空图的 UI 提示（没有引导用户去点 tab 弹日历的提示文案）

## 测试

- 手动验证：从 minute / multiday / dayK 切换到 overlay → 日历不弹出。
- 手动验证：在 overlay tab 上点 tab → 日历弹出；再点一次 → 日历关闭。
- 不预期新增单元测试，因为点击处理是内联匿名函数，单测价值低；改动也只是删一行。
