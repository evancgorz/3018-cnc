import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    signal openZProbeWizard()
    property var appPalette: ({ surface: "#22252B", raised: "#2B2F36", divider: "#3A3F48", text: "#F2F4F7", muted: "#A8AFBA", subtle: "#737B87", warning: "#F5B942" })
    modal: true
    title: "Commissioning"
    width: 720
    height: Math.min(620, (ApplicationWindow.window ? ApplicationWindow.window.contentItem.height - 24 : 620))
    x: Math.round(((ApplicationWindow.window ? ApplicationWindow.window.width : 1500) - width) / 2)
    y: Math.max(12, Math.round(((ApplicationWindow.window ? ApplicationWindow.window.contentItem.height : 674) - height) / 2))
    standardButtons: Dialog.NoButton
    background: Rectangle { color: dialog.appPalette.surface; radius: 12; border.color: dialog.appPalette.divider; border.width: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 12

        Label { text: "Bring declared hardware online one capability at a time."; color: dialog.appPalette.text; font.pixelSize: 17; font.weight: Font.DemiBold }

        ScrollView {
            id: contentScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: contentScroll.availableWidth > 0 ? contentScroll.availableWidth : dialog.width - 44
                spacing: 12

                Label { text: "Commissioning records evidence against the active machine configuration. A reset, disconnect, or safety-relevant profile change makes motion-derived evidence stale."; color: dialog.appPalette.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 86; radius: 9; color: dialog.appPalette.raised
                    ColumnLayout { anchors.fill: parent; anchors.margins: 14
                        Label { text: "Active machine"; color: dialog.appPalette.subtle; font.pixelSize: 11 }
                        Label { text: appViewModel ? appViewModel.profile_summary : ""; color: dialog.appPalette.text }
                        Label { text: appViewModel ? appViewModel.machine_capabilities : ""; color: dialog.appPalette.muted }
                    }
                }

                Label { visible: appViewModel && appViewModel.machine_capabilities.endsWith("none"); text: "No optional capabilities are enabled for this machine. Manual reference and work-zero operation remain available."; color: dialog.appPalette.warning; wrapMode: Text.Wrap; Layout.fillWidth: true }

                Rectangle { visible: appViewModel && appViewModel.z_touch_plate_enabled; Layout.fillWidth: true; Layout.preferredHeight: probeContent.implicitHeight + 28; radius: 9; color: dialog.appPalette.raised
                    ColumnLayout { id: probeContent; anchors.fill: parent; anchors.margins: 14; spacing: 8
                        Label { text: "Movable Z touch plate / puck"; color: dialog.appPalette.text; font.weight: Font.DemiBold }
                        Label { text: "Status: " + (appViewModel ? appViewModel.z_touch_plate_status_text : "unknown"); color: dialog.appPalette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: appViewModel ? appViewModel.z_touch_plate_input_message : ""; color: dialog.appPalette.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Manually touch the conductive cutter to the puck while watching the input. This verifies the probe type and wiring without moving an axis."; color: dialog.appPalette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        ColumnLayout { Layout.fillWidth: true; spacing: 6
                            Button { Layout.fillWidth: true; text: "Open Z-probe input wizard…"; enabled: appViewModel && appViewModel.connected; onClicked: dialog.openZProbeWizard() }
                            Label { Layout.fillWidth: true; text: "Plate: " + (appViewModel ? Number(appViewModel.z_touch_plate_thickness).toFixed(3) + " mm" : "—"); color: dialog.appPalette.muted }
                        }
                        Label { text: "Pine records each successful supervised probe automatically. Repeat until all three samples pass; no values need to be copied or entered manually."; color: dialog.appPalette.subtle; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label {
                            Layout.fillWidth: true
                            text: appViewModel ? ("Samples completed: " + appViewModel.z_touch_plate_sample_count + " of 3") : "Samples completed: 0 of 3"
                            color: dialog.appPalette.text
                            font.weight: Font.DemiBold
                        }
                        Button {
                            Layout.fillWidth: true
                            text: appViewModel && appViewModel.z_touch_plate_status === "ready"
                                  ? "Commissioning complete"
                                  : "Run supervised sample " + (appViewModel ? appViewModel.z_touch_plate_sample_count + 1 : 1) + " of 3"
                            enabled: appViewModel && appViewModel.connected && appViewModel.z_touch_plate_status === "needs commissioning"
                            onClicked: appViewModel.commissioning_z_touch_plate_sample()
                        }
                    }
                }

                Label { text: "Per-axis homing/limit declarations are available in Machine Setup. The Auto XYZ fixture and E-stop exercises are simulation-only digital-twin capabilities; physical commissioning remains explicit and must be performed separately. Hardware-free validation never certifies physical safety."; color: dialog.appPalette.subtle; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
        }

        RowLayout { Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button { text: "Close"; onClicked: dialog.close() }
        }
    }
}
