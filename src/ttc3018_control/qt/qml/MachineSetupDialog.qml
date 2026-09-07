import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

Dialog {
    id: dialog
    property var appPalette: ({ background: "#181A1F", surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942", accent: "#168BFF" })
    property bool switchesEnabled: false
    property bool zPlateEnabled: false
    property bool zPlateActiveLow: false
    property bool toolSetterEnabled: false
    property bool movableXyzEnabled: false
    property bool fixedFixtureEnabled: false
    modal: true
    title: "Machine setup"
    width: 720
    height: Math.min(620, (ApplicationWindow.window ? ApplicationWindow.window.contentItem.height - 24 : 620))
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.max(12, Math.round(((ApplicationWindow.window ? ApplicationWindow.window.contentItem.height : 674) - height) / 2))
    standardButtons: Dialog.NoButton
    onOpened: {
        zPlateEnabled = appViewModel && appViewModel.z_touch_plate_enabled
        zPlateActiveLow = appViewModel && appViewModel.z_touch_plate_active_low
        toolSetterEnabled = false
        switchesEnabled = false
        movableXyzEnabled = false
        fixedFixtureEnabled = false
    }
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
            ScrollView {
                id: hardwareScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth

                ColumnLayout {
                    width: hardwareScroll.availableWidth
                    spacing: 10
                    Label { text: "Optional hardware"; color: dialog.appPalette.text; font.weight: Font.DemiBold }
                    ModernCheckBox { palette: dialog.appPalette; text: "Movable Z touch plate / puck"; checked: dialog.zPlateEnabled; onToggled: dialog.zPlateEnabled = checked }
                    Label { text: "Place the rigid conductive puck flat on the workpiece for each probe, then remove it before machining. This is different from a permanently mounted tool setter."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    GridLayout { columns: 2; Layout.fillWidth: true; columnSpacing: 10; rowSpacing: 6; visible: dialog.zPlateEnabled
                    Label { text: "Plate thickness (mm)"; color: dialog.appPalette.muted }
                    TextField { id: plateThickness; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_thickness || 0) : "0"; validator: DoubleValidator { bottom: 0.001; top: 100 } }
                    Label { text: "Fast feed (mm/min)"; color: dialog.appPalette.muted }
                    TextField { id: plateFastFeed; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_fast_feed) : "100"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                    Label { text: "Slow feed (mm/min)"; color: dialog.appPalette.muted }
                    TextField { id: plateSlowFeed; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_slow_feed) : "25"; validator: DoubleValidator { bottom: 1; top: 1500 } }
                    Label { text: "Search distance (mm)"; color: dialog.appPalette.muted }
                    TextField { id: plateSearch; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_max_search) : "5"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                    Label { text: "Retract / clearance (mm)"; color: dialog.appPalette.muted }
                    TextField { id: plateRetract; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_retract) : "2"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                    Label { text: "Final safe retract (mm)"; color: dialog.appPalette.muted }
                    TextField { id: plateSafeRetract; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_safe_retract) : "2"; validator: DoubleValidator { bottom: 0.1; top: 100 } }
                    Label { text: "Repeatability tolerance (mm)"; color: dialog.appPalette.muted }
                    TextField { id: plateTolerance; Layout.fillWidth: true; text: appViewModel ? String(appViewModel.z_touch_plate_tolerance) : "0.05"; validator: DoubleValidator { bottom: 0.001; top: 10 } }
                }
                    ModernCheckBox { id: plateActiveLow; palette: dialog.appPalette; visible: dialog.zPlateEnabled; checked: dialog.zPlateActiveLow; onToggled: dialog.zPlateActiveLow = checked; text: "Invert probe input polarity in GRBL ($6)" }
                    Label { visible: dialog.zPlateEnabled; text: "Prefilled at 19.37 mm from your stated puck height — verify with calipers before probing."; color: dialog.appPalette.subtle; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    Button { visible: dialog.zPlateEnabled; Layout.fillWidth: true; text: "Save touch plate settings"; onClicked: if (appViewModel) appViewModel.save_z_touch_plate_settings(Number(plateThickness.text), dialog.zPlateActiveLow, Number(plateFastFeed.text), Number(plateSlowFeed.text), Number(plateSearch.text), Number(plateRetract.text), Number(plateSafeRetract.text), Number(plateTolerance.text)) }
                    Label { text: "Homing switches, fixed tool setters, and XYZ workpiece fixtures are temporarily hidden until they are implemented and hardware-tested."; color: dialog.appPalette.subtle; Layout.fillWidth: true; wrapMode: Text.Wrap }
                }
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
            Button { text: "Save declarations"; onClicked: { if (appViewModel) appViewModel.save_z_touch_plate_capability(dialog.zPlateEnabled); dialog.close() } }
            Button { text: "Close"; onClicked: dialog.close() }
        }
    }
}
