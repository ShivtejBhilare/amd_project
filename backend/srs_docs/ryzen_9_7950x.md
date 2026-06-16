# Ryzen 9 7950X Software Requirement Specification

## Power and Thermals
- Designed to run at 95C under heavy multi-threaded loads (TJMax). This is normal operating behavior.
- Uses AM5 socket.
- **Troubleshooting Thermals**: If a user complains about 95C temps during rendering, inform them this is by design for maximum performance. If temps exceed 95C and the system crashes, instruct them to check the AIO pump. If the pump is fine, escalate to CPU Performance team.

## Memory Controller
- Sweet spot for DDR5 is 6000MT/s with EXPO enabled.
- **Troubleshooting Boot Times**: Long memory training times on first boot or EXPO enable. Tell the user to wait up to 5 minutes or enable Memory Context Restore in BIOS.
