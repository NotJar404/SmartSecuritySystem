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
            // SAMPLE DATA (replace with DB later)
            var logs = new List<AccessLog>
            {
                new AccessLog
                {
                    FullName = "Maria Santos",
                    StudentId = "QCU-2024-0123",
                    Location = "Computer Laboratory 1",
                    Timestamp = DateTime.Now.AddSeconds(-30),
                    IsAuthorized = true,
                    ImageUrl = "/images/user1.jpg"
                },
                new AccessLog
                {
                    FullName = "Juan Dela Cruz",
                    StudentId = "QCU-2024-0456",
                    Location = "Main Entrance",
                    Timestamp = DateTime.Now.AddMinutes(-2),
                    IsAuthorized = true,
                    ImageUrl = "/images/user2.jpg"
                }
            };

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
            // TODO: integrate MQTT / IoT
            return RedirectToAction("Index");
        }
    }
}