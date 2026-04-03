using Microsoft.AspNetCore.Mvc;
using System;
using System.Collections.Generic;
using WebApp.Models;

namespace WebApp.Controllers
{
    public class AccessController : Controller
    {
        public IActionResult Index()
        {
            // SAMPLE DATA (Simulating real system logs)
            var logs = new List<AccessLog>
            {
                new AccessLog
                {
                    Id = 1,
                    FullName = "Maria Santos",
                    StudentId = "QCU-2024-0123",
                    Department = "BSIT",
                    Email = "maria.santos@qcu.edu.ph",
                    Phone = "09123456789",

                    Room = "Room 402",
                    Location = "Computer Laboratory 1",
                    Timestamp = DateTime.Now.AddSeconds(-30),

                    RFIDMatched = true,
                    FaceMatched = true,
                    IsAuthorized = true,

                    ImageUrl = "/images/user1.jpg"
                },

                new AccessLog
                {
                    Id = 2,
                    FullName = "Juan Dela Cruz",
                    StudentId = "QCU-2024-0456",
                    Department = "Engineering",
                    Email = "juan.delacruz@qcu.edu.ph",
                    Phone = "09987654321",

                    Room = "Main Entrance",
                    Location = "QCU Main Building",
                    Timestamp = DateTime.Now.AddMinutes(-2),

                    RFIDMatched = true,
                    FaceMatched = false, // Face mismatch
                    IsAuthorized = false,

                    ImageUrl = "/images/user2.jpg"
                },

                new AccessLog
                {
                    Id = 3,
                    FullName = "Unknown User",
                    StudentId = "N/A",
                    Department = "-",
                    Email = "-",
                    Phone = "-",

                    Room = "Restricted Room",
                    Location = "Server Room",
                    Timestamp = DateTime.Now.AddMinutes(-5),

                    RFIDMatched = false,
                    FaceMatched = false,
                    IsAuthorized = false,

                    ImageUrl = "/images/default-user.png"
                }
            };

            // Door Status (for IoT control)
            var door = new DoorStatus
            {
                DoorName = "Main Entrance Door",
                Location = "QCU Main Building",
                IsLocked = true
            };

            ViewBag.Door = door;

            return View(logs);
        }

        [HttpPost]
        public IActionResult UnlockDoor()
        {
            // 🔌 FUTURE: Integrate Raspberry Pi / MQTT / GPIO
            // Example:
            // Send unlock signal to Raspberry Pi

            TempData["Message"] = "Door unlocked successfully.";

            return RedirectToAction("Index");
        }
    }
}