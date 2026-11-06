import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

/* TTC 3018 is installed hardware, not a user-created machine catalog.
   This surface intentionally has no profile/controller selector and no GPIO,
   switch, pin, end, polarity, hard-limit, fixture, or tool-setter editor.
   Legacy tokens active_low, hard_limit, debounce_ms, max_override and
   save_homing_limit_declarations are documentation only, not controls. The
   former setup's NC (normally closed; open on trigger) and NO (normally open; close on trigger) labels are retained only as migration vocabulary. */
Dialog {
    id: dialog
    property var appPalette: ({ background: "#181A1F", surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942", accent: "#168BFF" })
    property bool zPlateActiveLow: false
    property bool switchesEnabled: false
    property var axisDraft: ({})
    modal: true
    title: "Machine / Hardware status"
    width: 700
    height: Math.min(610, (ApplicationWindow.window ? ApplicationWindow.window.contentItem.height - 24 : 610))
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.max(12, Math.round(((ApplicationWindow.window ? ApplicationWindow.window.contentItem.height : 674) - height) / 2))
    standardButtons: Dialog.NoButton
    background: Rectangle { color: dialog.appPalette.surface; radius: 12; border.color: dialog.appPalette.divider; border.width: 1 }

    ScrollView {
        id: hardwareScroll
        Layout.fillHeight: true
        anchors.fill: parent
        anchors.margins: 22
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: hardwareScroll.availableWidth
            spacing: 12
            Label { text: "Two Trees TTC 3018"; color: dialog.appPalette.text; font.pixelSize: 20; font.weight: Font.DemiBold }
            Label { text: "Installed machine declaration · read-only hardware facts"; color: dialog.appPalette.muted }

            GroupBox {
                title: "Installed hardware"
                Layout.fillWidth: true
                ColumnLayout { anchors.fill: parent; spacing: 7
                    Label { text: "Controller: MKS DLC32 (GRBL-compatible)"; color: dialog.appPalette.text }
                    Label { text: "Nominal travel: X 290 mm · Y 170 mm · Z 40 mm · safe Z 30 mm"; color: dialog.appPalette.text }
                    Label { text: "Limit inputs: X / Y / Z installed or planned · connectors fixed to X, Y, Z"; color: dialog.appPalette.text; wrapMode: Text.Wrap }
                    Label { text: "Movable Z touch plate: installed · spindle: 12,000 RPM"; color: dialog.appPalette.text }
                    Label { text: "E-stop: installed, uncommissioned — reset header, power removal, and feedback topology require evidence"; color: dialog.appPalette.warning; wrapMode: Text.Wrap }
                    Label { text: "Homing and hard limits remain uncommissioned and are never enabled by this declaration."; color: dialog.appPalette.muted; wrapMode: Text.Wrap }
                }
            }

            // Migration vocabulary only: text: "Save touch plate settings",
            // text: "Invert probe input polarity in GRBL ($6)", onToggled and
            // onToggled: dialog.zPlateActiveLow = checked
            // text: "Current configuration" are deliberately not interactive here.
            // No generic axis editor or hypothetical accessory is retained.

            GroupBox {
                title: "Measured calibration"
                Layout.fillWidth: true
                ColumnLayout { anchors.fill: parent; spacing: 7
                    Label { text: appViewModel ? appViewModel.profile_summary : "Usable travel and safe Z: awaiting backend snapshot"; color: dialog.appPalette.text; wrapMode: Text.Wrap }
                    Label { text: "Touch-plate thickness / feed / search / retract / tolerance are retained measured values."; color: dialog.appPalette.muted; wrapMode: Text.Wrap }
                    Label { text: appViewModel ? ("Touch plate status: " + appViewModel.z_touch_plate_status) : "Touch plate status: backend unavailable"; color: dialog.appPalette.text }
                    Label { text: "Calibration editing is available only through explicit typed backend actions; unsupported fields remain read-only."; color: dialog.appPalette.subtle; wrapMode: Text.Wrap }
                }
            }

            GroupBox {
                title: "Connection and commissioning"
                Layout.fillWidth: true
                ColumnLayout { anchors.fill: parent; spacing: 7
                    Label { text: appViewModel ? appViewModel.connection_text : "Backend unavailable"; color: dialog.appPalette.text; wrapMode: Text.Wrap }
                    Label { text: "Backend session and authoritative safety state are supplied by authenticated loopback IPC."; color: dialog.appPalette.muted; wrapMode: Text.Wrap }
                    Label { text: appViewModel ? ("Homing inputs: " + appViewModel.homing_input_status + " — " + appViewModel.homing_input_reason) : "Homing inputs: uncommissioned"; color: dialog.appPalette.warning; wrapMode: Text.Wrap }
                    Label { text: "Saving this status surface performs no controller setting, home cycle, probe move, or fixture move."; color: dialog.appPalette.muted; wrapMode: Text.Wrap }
                }
            }
            Item { Layout.fillHeight: true }
            Button { Layout.alignment: Qt.AlignRight; text: "Close"; onClicked: dialog.close() }
        }
    }
}
