import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    property var appPalette: ({ background: "#181A1F", surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942", accent: "#168BFF" })
    property bool switchesEnabled: false
    property bool zPlateEnabled: false
    property bool toolSetterEnabled: false
    property bool movableXyzEnabled: false
    property bool fixedFixtureEnabled: false
    modal: true
    title: "Machine setup"
    width: 720
    height: 620
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.height : 920) - height) / 2)
    standardButtons: Dialog.NoButton
    background: Rectangle { color: dialog.appPalette.surface; radius: 12; border.color: dialog.appPalette.divider; border.width: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 12
        Label { text: "Configure the hardware that is actually installed on this machine."; color: dialog.appPalette.text; font.pixelSize: 17; font.weight: Font.DemiBold }
        Label { text: "Every optional capability starts disabled. Save declarations first, then use Commissioning to test them before production controls become available."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
        TabBar { id: setupTabs; Layout.fillWidth: true
            TabButton { text: "Identity" }
            TabButton { text: "Axes" }
            TabButton { text: "Hardware" }
            TabButton { text: "Review" }
        }
        StackLayout { currentIndex: setupTabs.currentIndex; Layout.fillWidth: true; Layout.fillHeight: true
            ColumnLayout { spacing: 10
                Label { text: "Active machine"; color: dialog.appPalette.subtle; font.pixelSize: 11 }
                ComboBox { Layout.fillWidth: true; model: appViewModel ? appViewModel.machine_profiles : []; onActivated: appViewModel.select_machine(currentText) }
                Label { text: "Controller: GRBL 1.1"; color: dialog.appPalette.muted }
                Label { text: "The current controller adapter supports ordinary motion. Homing, probing, tool setting, and fixtures are shown only when declared, commissioned, and supported."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Item { Layout.fillHeight: true }
            }
            ColumnLayout { spacing: 10
                Label { text: "Travel and safety geometry"; color: dialog.appPalette.text; font.weight: Font.DemiBold }
                Label { text: appViewModel ? appViewModel.profile_summary : ""; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label { text: "Edit the measured travel and safe-Z values with Machine profile. Axis direction and switch details will be expanded here as capabilities are configured."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Item { Layout.fillHeight: true }
            }
            ColumnLayout { spacing: 10
                Label { text: "Optional hardware"; color: dialog.appPalette.text; font.weight: Font.DemiBold }
                CheckBox { text: "Limit switches and automatic homing"; checked: dialog.switchesEnabled; onToggled: dialog.switchesEnabled = checked }
                CheckBox { text: "Movable Z touch plate"; checked: dialog.zPlateEnabled; onToggled: dialog.zPlateEnabled = checked }
                CheckBox { text: "Fixed tool setter"; checked: dialog.toolSetterEnabled; onToggled: dialog.toolSetterEnabled = checked }
                CheckBox { text: "Movable XYZ probe"; checked: dialog.movableXyzEnabled; onToggled: dialog.movableXyzEnabled = checked }
                CheckBox { text: "Fixed XYZ fixture"; checked: dialog.fixedFixtureEnabled; onToggled: dialog.fixedFixtureEnabled = checked }
                Label { text: "Switches use one input per axis in this first adapter. Pin polarity, end selection, probe dimensions, and fixture approach geometry are commissioned separately."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Item { Layout.fillHeight: true }
            }
            ColumnLayout { spacing: 10
                Label { text: "Current configuration"; color: dialog.appPalette.text; font.weight: Font.DemiBold }
                Label { text: appViewModel ? appViewModel.machine_capabilities : ""; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Label { text: "Commissioning status: " + (appViewModel ? appViewModel.homing_state : "unknown"); color: dialog.appPalette.muted }
                Label { text: "No controller setting, home cycle, probe move, or fixture move is performed by saving this setup."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Item { Layout.fillHeight: true }
            }
        }
        RowLayout { Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Save declarations"; onClicked: { if (appViewModel) appViewModel.save_machine_capabilities(dialog.switchesEnabled, dialog.zPlateEnabled, dialog.toolSetterEnabled, dialog.movableXyzEnabled, dialog.fixedFixtureEnabled); dialog.close() } }
            Button { text: "Close"; onClicked: dialog.close() }
        }
    }
}
