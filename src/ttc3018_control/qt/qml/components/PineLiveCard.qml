import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    required property var palette
    implicitHeight: 58
    implicitWidth: 210

    Rectangle { anchors.fill: parent; radius: 12; color: root.palette.surface; border.color: root.palette.divider; border.width: 1 }
    RowLayout {
        anchors.fill: parent; anchors.margins: 10; spacing: 8
            Label { text: "Pine Live"; color: root.palette.text; font.pixelSize: 14; font.weight: Font.DemiBold }
            Label { text: appViewModel ? appViewModel.live_access_state : "Off"; color: root.palette.muted; font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight }
            LiveSecondaryButton { text: "Camera"; onClicked: appViewModel && appViewModel.live_camera_state !== "off" ? appViewModel.stop_live_viewer() : appViewModel.open_live_viewer() }
            LivePrimaryButton { text: "Open Pine Live"; onClicked: viewerDialog.open() }
    }

    Dialog {
        id: viewerDialog
        modal: true; title: "Pine Live"
        width: Math.min(760, window.width - 32)
        height: Math.min(650, window.height - 32)
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.NoButton
        background: Rectangle { color: root.palette.surface; radius: 14; border.color: root.palette.divider; border.width: 1 }
        ColumnLayout { anchors.fill: parent; anchors.margins: 18; spacing: 12
            RowLayout { Layout.fillWidth: true
                Label { text: "Live viewer"; color: root.palette.text; font.pixelSize: 22; font.weight: Font.Bold }
                Item { Layout.fillWidth: true }
                LiveSecondaryButton { text: "Close"; onClicked: viewerDialog.close() }
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 310; color: "#0D1014"; radius: 10; clip: true
                Image { anchors.fill: parent; source: appViewModel ? appViewModel.live_camera_frame : ""; fillMode: Image.PreserveAspectFit }
                Label { anchors.centerIn: parent; text: appViewModel ? appViewModel.live_camera_state : "Camera off"; color: root.palette.muted; visible: !appViewModel || appViewModel.live_camera_state === "off" }
            }
            RowLayout { Layout.fillWidth: true; spacing: 10
                Label { text: appViewModel ? appViewModel.connection_text : "Disconnected"; color: root.palette.text }
                Label { text: appViewModel ? appViewModel.job_state + " · " + appViewModel.job_progress + "%" : ""; color: root.palette.accent }
                Item { Layout.fillWidth: true }
                ComboBox {
                    id: cameraSelector
                    visible: appViewModel && appViewModel.live_cameras.length > 0
                    enabled: appViewModel && appViewModel.live_camera_state === "off"
                    model: appViewModel ? appViewModel.live_cameras : []
                    currentIndex: {
                        if (!appViewModel || appViewModel.live_cameras.length === 0) return -1
                        var selected = appViewModel.live_camera_name
                        var index = appViewModel.live_cameras.indexOf(selected)
                        return index >= 0 ? index : 0
                    }
                    Layout.preferredWidth: 190
                    onActivated: appViewModel.select_live_camera(currentText)
                }
                LiveSecondaryButton { text: appViewModel && appViewModel.live_camera_state !== "off" ? "Stop camera" : "Start camera"; onClicked: appViewModel && appViewModel.live_camera_state !== "off" ? appViewModel.stop_live_viewer() : appViewModel.open_live_viewer() }
            }
            LiveDivider {}
            LiveSectionTitle { text: "Remote access" }
            LiveMutedLabel { text: "Pair an iPhone or other device over your private Tailscale network. Pine remains the only controller of the CNC." }
            RowLayout { Layout.fillWidth: true
            Label { text: appViewModel ? appViewModel.live_access_state : "Off"; color: appViewModel && appViewModel.live_access_enabled ? root.palette.success : root.palette.muted; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Item { Layout.fillWidth: true }
                LiveSecondaryButton { text: "Regenerate access"; enabled: appViewModel && appViewModel.live_access_enabled; onClicked: appViewModel.regenerate_live_pairing() }
                LiveSecondaryButton { text: "Disable"; enabled: appViewModel && appViewModel.live_access_enabled; onClicked: appViewModel.disable_live_access() }
                LivePrimaryButton { text: "Enable mobile"; visible: !appViewModel || !appViewModel.live_access_enabled; onClicked: enableDialog.open() }
            }
            RowLayout { Layout.fillWidth: true; visible: appViewModel && appViewModel.live_access_enabled
                Image { source: appViewModel ? appViewModel.live_qr_data : ""; sourceSize.width: 112; sourceSize.height: 112; fillMode: Image.PreserveAspectFit; Layout.preferredWidth: 112; Layout.preferredHeight: 112 }
                ColumnLayout { Layout.fillWidth: true
                    Label { text: "Pairing code"; color: root.palette.muted; font.pixelSize: 11 }
                    Label { text: appViewModel ? appViewModel.live_pairing_code : ""; color: root.palette.text; font.pixelSize: 26; font.weight: Font.Bold; font.family: "Cascadia Mono" }
                    Label { text: appViewModel ? appViewModel.live_url : ""; color: root.palette.accent; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    Label { text: appViewModel ? appViewModel.live_session_count + " paired · " + appViewModel.live_viewer_count + " viewing" : ""; color: root.palette.muted }
                }
            }
        }
    }

    Dialog { id: enableDialog; modal: true; title: "Enable Pine Live?"; width: Math.min(500, window.width - 32); height: Math.min(260, window.height - 32); anchors.centerIn: Overlay.overlay; standardButtons: Dialog.NoButton
        background: Rectangle { color: root.palette.surface; radius: 12; border.color: root.palette.divider; border.width: 1 }
        ColumnLayout { anchors.fill: parent; anchors.margins: 20; spacing: 12
            Label { text: "This publishes Pine Live through your private Tailscale network. Paired devices can view status and use Pause, Resume, and the guarded Abort action."; color: root.palette.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
            LiveMutedLabel { text: "Tailscale must be installed and signed in on this computer and the phone. Keep a physical emergency stop available." }
            LiveSecondaryButton { visible: appViewModel && !appViewModel.tailscale_installed; text: "Install Tailscale for Windows"; onClicked: Qt.openUrlExternally(appViewModel.tailscale_download_url) }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                LiveSecondaryButton { text: "Cancel"; onClicked: enableDialog.close() }
                LivePrimaryButton { text: "Enable"; onClicked: { appViewModel.enable_live_access(); enableDialog.close() } }
            }
        }
    }

    component LivePrimaryButton: Button {
        id: primary
        implicitHeight: 36; padding: 12
        contentItem: Text { text: primary.text; color: root.palette.text; font: primary.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { radius: 8; color: primary.down ? "#086FCC" : primary.hovered ? root.palette.accentHover : root.palette.accent }
    }
    component LiveSecondaryButton: Button {
        id: secondary
        implicitHeight: 34; padding: 10
        contentItem: Text { text: secondary.text; color: secondary.enabled ? root.palette.text : root.palette.subtle; font: secondary.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { radius: 8; color: secondary.down ? "#20242A" : secondary.hovered ? root.palette.hover : root.palette.raised; border.color: root.palette.divider; border.width: 1 }
    }
    component LiveSectionTitle: Label { color: root.palette.text; font.pixelSize: 14; font.weight: Font.DemiBold }
    component LiveMutedLabel: Label { color: root.palette.muted; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
    component LiveDivider: Rectangle { Layout.fillWidth: true; height: 1; color: root.palette.divider }
}
