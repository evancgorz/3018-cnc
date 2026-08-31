import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    property var appPalette: ({ surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942" })
    modal: true
    title: "Commissioning"
    width: 720
    height: Math.min(560, (ApplicationWindow.window ? ApplicationWindow.window.contentItem.height - 24 : 560))
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.max(12, Math.round(((ApplicationWindow.window ? ApplicationWindow.window.contentItem.height : 674) - height) / 2))
    standardButtons: Dialog.NoButton
    background: Rectangle { color: dialog.appPalette.surface; radius: 12; border.color: dialog.appPalette.divider; border.width: 1 }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 22; spacing: 12
        Label { text: "Bring declared hardware online one capability at a time."; color: dialog.appPalette.text; font.pixelSize: 17; font.weight: Font.DemiBold }
        Label { text: "Commissioning records evidence against the active machine configuration. A reset, disconnect, or safety-relevant profile change makes motion-derived evidence stale."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 86; radius: 9; color: dialog.appPalette.raised
            ColumnLayout { anchors.fill: parent; anchors.margins: 14
                Label { text: "Active machine"; color: dialog.appPalette.subtle; font.pixelSize: 11 }
                Label { text: appViewModel ? appViewModel.profile_summary : ""; color: dialog.appPalette.text }
                Label { text: appViewModel ? appViewModel.machine_capabilities : ""; color: dialog.appPalette.muted }
            }
        }
        Label { visible: appViewModel && appViewModel.machine_capabilities.endsWith("none"); text: "No optional capabilities are enabled for this machine. Manual reference and work-zero operation remain available."; color: dialog.appPalette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { text: "Homing: " + (appViewModel ? appViewModel.homing_state : "unknown"); color: dialog.appPalette.muted }
        Button { text: "Home machine"; enabled: appViewModel && appViewModel.can_home_machine; onClicked: appViewModel.home_machine() }
        Label { text: "Homing requires one commissioned switch per axis and an explicit operator action. Probe and fixed-fixture commissioning will appear when those capabilities are declared."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
        Item { Layout.fillHeight: true }
        RowLayout { Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Close"; onClicked: dialog.close() }
        }
    }
}
