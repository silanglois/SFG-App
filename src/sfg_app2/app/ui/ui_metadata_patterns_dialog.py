# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'pattern_editor_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QDialog,
    QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QTextEdit,
    QVBoxLayout, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(652, 532)
        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.splitter = QSplitter(Dialog)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.widget = QWidget(self.splitter)
        self.widget.setObjectName(u"widget")
        self.verticalLayout_2 = QVBoxLayout(self.widget)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.label = QLabel(self.widget)
        self.label.setObjectName(u"label")

        self.verticalLayout_2.addWidget(self.label)

        self.savedPatternsPlaceholder = QWidget(self.widget)
        self.savedPatternsPlaceholder.setObjectName(u"savedPatternsPlaceholder")

        self.verticalLayout_2.addWidget(self.savedPatternsPlaceholder)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.pushButton_2 = QPushButton(self.widget)
        self.pushButton_2.setObjectName(u"pushButton_2")

        self.horizontalLayout_2.addWidget(self.pushButton_2)

        self.deactivateButton = QPushButton(self.widget)
        self.deactivateButton.setObjectName(u"deactivateButton")

        self.horizontalLayout_2.addWidget(self.deactivateButton)


        self.verticalLayout_2.addLayout(self.horizontalLayout_2)

        self.conflictWarningLabel = QLabel(self.widget)
        self.conflictWarningLabel.setObjectName(u"conflictWarningLabel")
        self.conflictWarningLabel.setEnabled(False)
        self.conflictWarningLabel.setStyleSheet(u"color: rgb(255, 85, 0);")
        self.conflictWarningLabel.setWordWrap(True)

        self.verticalLayout_2.addWidget(self.conflictWarningLabel)

        self.activeLengthsLabel = QLabel(self.widget)
        self.activeLengthsLabel.setObjectName(u"activeLengthsLabel")

        self.verticalLayout_2.addWidget(self.activeLengthsLabel)

        self.splitter.addWidget(self.widget)
        self.widget_2 = QWidget(self.splitter)
        self.widget_2.setObjectName(u"widget_2")
        self.verticalLayout_3 = QVBoxLayout(self.widget_2)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.label_2 = QLabel(self.widget_2)
        self.label_2.setObjectName(u"label_2")
        font = QFont()
        font.setBold(True)
        self.label_2.setFont(font)

        self.verticalLayout_3.addWidget(self.label_2)

        self.patternNamemLineEdit = QLineEdit(self.widget_2)
        self.patternNamemLineEdit.setObjectName(u"patternNamemLineEdit")

        self.verticalLayout_3.addWidget(self.patternNamemLineEdit)

        self.label_3 = QLabel(self.widget_2)
        self.label_3.setObjectName(u"label_3")

        self.verticalLayout_3.addWidget(self.label_3)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.fieldsListWidget = QListWidget(self.widget_2)
        self.fieldsListWidget.setObjectName(u"fieldsListWidget")
        self.fieldsListWidget.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.fieldsListWidget.setDragEnabled(True)
        self.fieldsListWidget.setDragDropMode(QAbstractItemView.InternalMove)

        self.horizontalLayout_4.addWidget(self.fieldsListWidget)

        self.verticalLayout_4 = QVBoxLayout()
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.moveUpButton = QPushButton(self.widget_2)
        self.moveUpButton.setObjectName(u"moveUpButton")

        self.verticalLayout_4.addWidget(self.moveUpButton)

        self.moveDownButton = QPushButton(self.widget_2)
        self.moveDownButton.setObjectName(u"moveDownButton")

        self.verticalLayout_4.addWidget(self.moveDownButton)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_4.addItem(self.verticalSpacer)


        self.horizontalLayout_4.addLayout(self.verticalLayout_4)


        self.verticalLayout_3.addLayout(self.horizontalLayout_4)

        self.addFieldButton = QPushButton(self.widget_2)
        self.addFieldButton.setObjectName(u"addFieldButton")

        self.verticalLayout_3.addWidget(self.addFieldButton)

        self.frame = QFrame(self.widget_2)
        self.frame.setObjectName(u"frame")
        self.frame.setFrameShape(QFrame.HLine)
        self.frame.setFrameShadow(QFrame.Sunken)

        self.verticalLayout_3.addWidget(self.frame)

        self.label_4 = QLabel(self.widget_2)
        self.label_4.setObjectName(u"label_4")

        self.verticalLayout_3.addWidget(self.label_4)

        self.previewFilenameLineEdit = QLineEdit(self.widget_2)
        self.previewFilenameLineEdit.setObjectName(u"previewFilenameLineEdit")

        self.verticalLayout_3.addWidget(self.previewFilenameLineEdit)

        self.label_5 = QLabel(self.widget_2)
        self.label_5.setObjectName(u"label_5")

        self.verticalLayout_3.addWidget(self.label_5)

        self.parsedResultTextEdit = QTextEdit(self.widget_2)
        self.parsedResultTextEdit.setObjectName(u"parsedResultTextEdit")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.parsedResultTextEdit.sizePolicy().hasHeightForWidth())
        self.parsedResultTextEdit.setSizePolicy(sizePolicy)
        self.parsedResultTextEdit.setMaximumSize(QSize(16777215, 120))
        self.parsedResultTextEdit.setReadOnly(True)

        self.verticalLayout_3.addWidget(self.parsedResultTextEdit)

        self.splitter.addWidget(self.widget_2)

        self.verticalLayout.addWidget(self.splitter)

        self.buttonBox = QDialogButtonBox(Dialog)
        self.buttonBox.setObjectName(u"buttonBox")
        self.buttonBox.setOrientation(Qt.Horizontal)
        self.buttonBox.setStandardButtons(QDialogButtonBox.Cancel|QDialogButtonBox.Ok)

        self.verticalLayout.addWidget(self.buttonBox)


        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"Dialog", None))
        self.label.setText(QCoreApplication.translate("Dialog", u"<html><head/><body><p><span style=\" font-weight:600;\">Saved Patterns</span></p></body></html>", None))
        self.pushButton_2.setText(QCoreApplication.translate("Dialog", u"\u2605 Set Active", None))
        self.deactivateButton.setText(QCoreApplication.translate("Dialog", u"\u2606 Deactivate", None))
        self.conflictWarningLabel.setText("")
        self.activeLengthsLabel.setText(QCoreApplication.translate("Dialog", u"Active lengths: none", None))
        self.label_2.setText(QCoreApplication.translate("Dialog", u"Pattern Name", None))
        self.label_3.setText(QCoreApplication.translate("Dialog", u"Fields", None))
        self.moveUpButton.setText(QCoreApplication.translate("Dialog", u"\u2191", None))
        self.moveDownButton.setText(QCoreApplication.translate("Dialog", u"\u2193", None))
        self.addFieldButton.setText(QCoreApplication.translate("Dialog", u"+ Add field", None))
        self.label_4.setText(QCoreApplication.translate("Dialog", u"Preview filename", None))
        self.previewFilenameLineEdit.setText(QCoreApplication.translate("Dialog", u"sample_ssp_3um_10s_1458.csv", None))
        self.label_5.setText(QCoreApplication.translate("Dialog", u"Parsed result", None))
    # retranslateUi

