# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_window.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QMainWindow, QMenu,
    QMenuBar, QSizePolicy, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(800, 600)
        self.actionLoad_file_s = QAction(MainWindow)
        self.actionLoad_file_s.setObjectName(u"actionLoad_file_s")
        self.actionLoad_files_from_folder = QAction(MainWindow)
        self.actionLoad_files_from_folder.setObjectName(u"actionLoad_files_from_folder")
        self.actionUse_metadata_patterns = QAction(MainWindow)
        self.actionUse_metadata_patterns.setObjectName(u"actionUse_metadata_patterns")
        self.actionUse_metadata_patterns.setCheckable(True)
        self.actionSet_metadata_patterns = QAction(MainWindow)
        self.actionSet_metadata_patterns.setObjectName(u"actionSet_metadata_patterns")
        self.actionAbout = QAction(MainWindow)
        self.actionAbout.setObjectName(u"actionAbout")
        self.actionDocs_tutorials = QAction(MainWindow)
        self.actionDocs_tutorials.setObjectName(u"actionDocs_tutorials")
        self.actionIgnore_selected_files = QAction(MainWindow)
        self.actionIgnore_selected_files.setObjectName(u"actionIgnore_selected_files")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.mainTabWidget = QTabWidget(self.centralwidget)
        self.mainTabWidget.setObjectName(u"mainTabWidget")
        self.loadmatchTab = QWidget()
        self.loadmatchTab.setObjectName(u"loadmatchTab")
        self.horizontalLayout = QHBoxLayout(self.loadmatchTab)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.loadmatchTabcontent = QWidget(self.loadmatchTab)
        self.loadmatchTabcontent.setObjectName(u"loadmatchTabcontent")

        self.horizontalLayout.addWidget(self.loadmatchTabcontent)

        self.mainTabWidget.addTab(self.loadmatchTab, "")
        self.tab_2 = QWidget()
        self.tab_2.setObjectName(u"tab_2")
        self.mainTabWidget.addTab(self.tab_2, "")

        self.verticalLayout.addWidget(self.mainTabWidget)

        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 800, 21))
        self.menuFile = QMenu(self.menubar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuPreferences = QMenu(self.menubar)
        self.menuPreferences.setObjectName(u"menuPreferences")
        self.menuHelp = QMenu(self.menubar)
        self.menuHelp.setObjectName(u"menuHelp")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuPreferences.menuAction())
        self.menubar.addAction(self.menuHelp.menuAction())
        self.menuFile.addAction(self.actionLoad_file_s)
        self.menuFile.addAction(self.actionLoad_files_from_folder)
        self.menuFile.addAction(self.actionIgnore_selected_files)
        self.menuPreferences.addAction(self.actionUse_metadata_patterns)
        self.menuPreferences.addAction(self.actionSet_metadata_patterns)
        self.menuHelp.addAction(self.actionAbout)
        self.menuHelp.addAction(self.actionDocs_tutorials)

        self.retranslateUi(MainWindow)

        self.mainTabWidget.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"SFG-App", None))
        self.actionLoad_file_s.setText(QCoreApplication.translate("MainWindow", u"Load file(s)", None))
        self.actionLoad_files_from_folder.setText(QCoreApplication.translate("MainWindow", u"Load files from folder", None))
        self.actionUse_metadata_patterns.setText(QCoreApplication.translate("MainWindow", u"Use metadata patterns", None))
        self.actionSet_metadata_patterns.setText(QCoreApplication.translate("MainWindow", u"Set metadata patterns", None))
        self.actionAbout.setText(QCoreApplication.translate("MainWindow", u"About", None))
        self.actionDocs_tutorials.setText(QCoreApplication.translate("MainWindow", u"Docs & tutorials", None))
        self.actionIgnore_selected_files.setText(QCoreApplication.translate("MainWindow", u"Ignore selected files", None))
        self.mainTabWidget.setTabText(self.mainTabWidget.indexOf(self.loadmatchTab), QCoreApplication.translate("MainWindow", u"Load/Match", None))
        self.mainTabWidget.setTabText(self.mainTabWidget.indexOf(self.tab_2), QCoreApplication.translate("MainWindow", u"Tab 2", None))
        self.menuFile.setTitle(QCoreApplication.translate("MainWindow", u"File", None))
        self.menuPreferences.setTitle(QCoreApplication.translate("MainWindow", u"Preferences", None))
        self.menuHelp.setTitle(QCoreApplication.translate("MainWindow", u"Help", None))
    # retranslateUi

