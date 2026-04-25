import { useViewStore } from "../../stores/view";

export function EmptyState() {
  const setView = useViewStore(s => s.setView);
  return (
    <div className="dashboard-empty">
      <p>还没有任何监听页。</p>
      <p>
        <button className="link-btn" onClick={() => setView("whop")}>跳转到 Whop 管理</button>
        {" "}添加你的第一个监听。
      </p>
    </div>
  );
}
