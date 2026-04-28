using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using System.Linq;
using System.Threading.Tasks;
using WebApp.Models;
using WebApp.Data;

namespace WebApp.Controllers
{
    public class AccessController : Controller
    {
        private readonly AppDbContext _context;

        public AccessController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // MAIN PAGE
        // =========================
        public async Task<IActionResult> Index()
        {
            var logs = await _context.AccessLogs
                .OrderByDescending(x => x.Timestamp)
                .Take(50)
                .ToListAsync(); // ✅ Fetch first

            // ✅ Populate UI-only fields safely
            foreach (var log in logs)
            {
                log.FullName = log.FullName ?? "Unknown User";
                log.PersonnelId = log.PersonnelId ?? "N/A";
                log.Department = log.Department ?? "-";
                log.Email = log.Email ?? "-";
                log.Phone = log.Phone ?? "-";
                log.Room = log.Room ?? "Unknown Room";
                log.Location = log.Location ?? "Unknown Location";
                log.ImageUrl = log.ImageUrl ?? "/images/default-user.png";
            }

            return View(logs);
        }

        // =========================
        // UNLOCK DOOR (POST)
        // =========================
        [HttpPost]
        public IActionResult UnlockDoor()
        {
            // 🔌 Future IoT integration here

            TempData["Message"] = "Door unlocked successfully.";
            return RedirectToAction(nameof(Index));
        }

        // =========================
        // API: GET LATEST LOGS
        // =========================
        [HttpGet]
        public async Task<IActionResult> GetLatestLogs()
        {
            var logs = await _context.AccessLogs
                .OrderByDescending(x => x.Timestamp)
                .Take(20)
                .ToListAsync(); // ✅ IMPORTANT FIX

            // ✅ Now safe to use NotMapped fields
            var result = logs.Select(log => new
            {
                FullName = log.FullName ?? "Unknown User",
                StudentId = log.PersonnelId ?? "N/A",
                Department = log.Department ?? "-",
                Email = log.Email ?? "-",
                Phone = log.Phone ?? "-",
                Room = log.Room ?? "Unknown Room",
                Location = log.Location ?? "Unknown Location",
                Time = log.Timestamp.ToString("hh:mm tt"),
                ImageUrl = log.ImageUrl ?? "/images/default-user.png",
                Status = log.Status
            });

            return Json(result);
        }
    }
}