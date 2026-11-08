"""공통 목업 소스에서 Desktop·Mobile 독립 HTML Fragment를 생성합니다."""

from pathlib import Path


def build_workspace_previews() -> None:
    """두 기기의 초기 상태와 고유 Root ID를 적용해 미리보기를 만듭니다."""
    mockup_directory = Path(__file__).resolve().parent
    shell_markup = (mockup_directory / "workspace-shell.html").read_text(encoding="utf-8")
    stylesheet = (mockup_directory / "workspace-preview.css").read_text(encoding="utf-8")
    behavior_script = (mockup_directory / "workspace-preview.js").read_text(encoding="utf-8")
    device_labels = {"desktop": "Desktop 스타일 구성 목업", "mobile": "Mobile 스타일 구성 목업"}

    for device_name, accessible_label in device_labels.items():
        root_identifier = f"style-workspace-{device_name}"
        device_markup = shell_markup.replace("__WORKSPACE_ROOT_ID__", root_identifier)
        device_markup = device_markup.replace("__WORKSPACE_DEVICE__", device_name)
        device_markup = device_markup.replace("__WORKSPACE_LABEL__", accessible_label)
        device_script = behavior_script.replace("__WORKSPACE_ROOT_ID__", root_identifier)
        if device_name == "mobile":
            device_markup = f'<div class="viz-dotted-background" style="padding:16px 0">\n{device_markup}</div>\n'

        fragment_content = f"<style>\n{stylesheet}</style>\n{device_markup}<script>\n{device_script}</script>\n"
        destination_path = mockup_directory / f"style-workspace-{device_name}.html"
        destination_path.write_text(fragment_content, encoding="utf-8", newline="\n")
        print(f"Created {destination_path.name}: {destination_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    build_workspace_previews()
