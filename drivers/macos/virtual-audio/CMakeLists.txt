cmake_minimum_required(VERSION 3.20)
project(VoxPassportVirtualAudio CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CODESIGN_ID "" CACHE STRING "Optional macOS codesign identity")

set(DRIVER_NAME "VoxPassportVirtualAudio")
set(DRIVER_VERSION "0.1.0")
set(DRIVER_IDENTIFIER "com.voxpassport.virtual-audio")
set(DRIVER_UID "69D56F23-8258-4A71-9D5A-746C84C55E3F")
set(DRIVER_ENTRYPOINT "VoxPassportEntryPoint")
set(LIBASPL_COMMIT "633e0f70203edd87d320fc5a3cae901e1363aac5")

include(ExternalProject)
ExternalProject_Add(voxpassport_libaspl
  GIT_REPOSITORY https://github.com/gavv/libASPL.git
  GIT_TAG ${LIBASPL_COMMIT}
  GIT_SHALLOW FALSE
  UPDATE_COMMAND ""
  CMAKE_ARGS -DCMAKE_INSTALL_PREFIX=<INSTALL_DIR> -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF
  INSTALL_DIR ${CMAKE_CURRENT_BINARY_DIR}/libASPL-prefix
)

add_library(${DRIVER_NAME} MODULE Driver.cpp)
add_dependencies(${DRIVER_NAME} voxpassport_libaspl)
target_include_directories(${DRIVER_NAME} PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/libASPL-prefix/include)
target_link_libraries(${DRIVER_NAME} PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/libASPL-prefix/lib/libASPL.a)

find_library(CORE_FOUNDATION_FRAMEWORK CoreFoundation REQUIRED)
find_library(CORE_AUDIO_FRAMEWORK CoreAudio REQUIRED)
target_link_libraries(${DRIVER_NAME} PRIVATE ${CORE_FOUNDATION_FRAMEWORK} ${CORE_AUDIO_FRAMEWORK})

set_target_properties(${DRIVER_NAME} PROPERTIES
  OUTPUT_NAME "${DRIVER_NAME}"
  BUNDLE true
  BUNDLE_EXTENSION "driver"
  PREFIX ""
  SUFFIX ""
  MACOSX_BUNDLE ON
  MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
  MACOSX_BUNDLE_BUNDLE_NAME "${DRIVER_NAME}"
  MACOSX_BUNDLE_BUNDLE_VERSION "${DRIVER_VERSION}"
  MACOSX_BUNDLE_GUI_IDENTIFIER "${DRIVER_IDENTIFIER}"
  MACOSX_BUNDLE_SHORT_VERSION_STRING "${DRIVER_VERSION}"
)

if(NOT CODESIGN_ID STREQUAL "")
  add_custom_command(TARGET ${DRIVER_NAME} POST_BUILD
    COMMAND codesign --force --deep --sign "${CODESIGN_ID}" "$<TARGET_BUNDLE_DIR:${DRIVER_NAME}>"
    COMMENT "Signing VoxPassportVirtualAudio.driver"
    VERBATIM)
endif()
