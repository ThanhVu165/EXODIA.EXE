/** Static export: FastAPI phục vụ thư mục out/. Không có Node runtime khi chạy. */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: false,
};
export default nextConfig;
