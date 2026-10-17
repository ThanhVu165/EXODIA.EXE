"use client";

import { useEffect, useState } from "react";

// Giai đoạn 1: trang khung để chứng minh static export + gọi API cùng origin.
export default function Home() {
  const [ping, setPing] = useState<string>("đang gọi /api/ping…");

  useEffect(() => {
    fetch("/api/ping")
      .then((r) => r.json())
      .then((j) => setPing(JSON.stringify(j)))
      .catch((e) => setPing(`lỗi: ${String(e)}`));
  }, []);

  return (
    <main>
      <div role="note" style={{ background: "#fff3cd", padding: "8px 16px", borderBottom: "1px solid #e0c36a" }}>
        Bản demo/sandbox, dữ liệu giả lập, không phải hệ thống chính thức của UEH.
      </div>
      <section style={{ padding: 16 }}>
        <h1>DSA Intelligence</h1>
        <p>Khung hạ tầng (Giai đoạn 1). Nghiệp vụ chưa được xây.</p>
        <p>
          <code>/api/ping</code>: <span id="ping-result">{ping}</span>
        </p>
      </section>
    </main>
  );
}
