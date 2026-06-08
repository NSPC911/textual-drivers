import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Textual Drivers Demo")
    parser.add_argument(
        "--demo",
        choices=["check-image-support", "key-test", "kitty-drag-out", "kitty-drag-in"],
        default="check-image-support",
        help="Choose a demo to run",
    )
    args = parser.parse_args()

    if args.demo == "check-image-support":
        from .capability_check_app import CapabilityCheckApp

        CapabilityCheckApp().run()
    elif args.demo == "key-test":
        from .test_app import DriverTestApp

        DriverTestApp().run()
    elif args.demo == "kitty-drag-out":
        from .drag_out import DragOutApp

        DragOutApp().run()
    elif args.demo == "kitty-drag-in":
        from .drag_in import DragInApp

        DragInApp().run()


if __name__ == "__main__":
    main()
