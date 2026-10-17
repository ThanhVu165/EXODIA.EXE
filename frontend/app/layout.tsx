import type { ReactNode } from "react";

export const metadata = {
  title: "DSA Intelligence (demo)",
  description: "Bản demo/sandbox — dữ liệu giả lập, không phải hệ thống chính thức của UEH",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
