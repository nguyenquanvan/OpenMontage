# MOSA TOOL ALL — chuyển máy và cập nhật Windows

## Cài cho máy nhân viên

1. Mở trang **Releases** của `nguyenquanvan/OpenMontage`.
2. Tải file `MOSA-TOOL-ALL-Setup-<version>-<build>-win-x64.exe`.
3. Chạy trình cài. Node.js, FFmpeg, ffprobe, uv và Remotion đã nằm trong bộ cài.
4. API key và model tải thêm được lưu riêng trên từng máy, không nằm trong GitHub hoặc bộ cài.

## Cập nhật app đã cài

Từ phiên bản `1.6.2`, app tự kiểm tra GitHub Releases khi khởi động và mỗi giờ. Khi có bản mới, app tải đúng bộ cài Windows, xác thực bằng `SHA256SUMS.txt`, rồi chờ workflow đang chạy hoàn tất trước khi cài. Thông báo và tiến độ cập nhật xuất hiện trong thư viện, board và trang Cài đặt API. Bạn vẫn có thể chọn **Cài đặt API → Phiên bản MOSA TOOL ALL → Kiểm tra bản mới** để kiểm tra ngay.

Trên macOS, app tự tải và xác thực DMG, nhưng bạn cần mở DMG và kéo app vào Applications để hoàn tất. Các bản cũ hơn `1.6.2` cần dùng nút cập nhật thủ công hoặc cài `1.6.2` một lần để bật kiểm tra định kỳ.

## Phát hành bản mới

1. Sửa `APP_VERSION` và `APP_BUILD` trong `lib/app_version.py`.
2. Commit toàn bộ thay đổi cần phát hành; tuyệt đối không commit `.env`, API key, model hoặc thư mục `projects/`.
3. Chạy thử:

   ```bash
   python scripts/publish_desktop_release.py
   ```

4. Phát hành:

   ```bash
   python scripts/publish_desktop_release.py --push
   ```

Tag `v<version>` sẽ kích hoạt GitHub Actions để tạo installer Windows, ZIP portable, DMG macOS, file phiên bản và SHA-256.

## Mang source sang máy Windows để làm tiếp

Chạy:

```bash
python scripts/package_source_transfer.py
```

File ZIP trong `dist/` chỉ lấy các file đã commit bằng `git archive`, nên không kèm `.env`, API key, cache, model, project media hoặc build cũ. Cách tốt hơn cho phát triển dài hạn là clone repository từ GitHub trên máy Windows.
