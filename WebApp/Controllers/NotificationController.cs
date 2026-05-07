using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System.Linq;
using System.Threading.Tasks;
using System.Security.Claims;
using System;

namespace WebApp.Controllers
{
    [Authorize]
    public class NotificationsController : Controller
    {
        private readonly AppDbContext _context;

        public NotificationsController(AppDbContext context)
        {
            _context = context;
        }

        // =====================================================
        // CURRENT USER HELPERS
        // =====================================================
        private string GetUserId()
        {
            return User.FindFirstValue(ClaimTypes.NameIdentifier) ?? "";
        }

        private string GetUserRole()
        {
            return User.FindFirstValue(ClaimTypes.Role) ?? "Security";
        }

        // =====================================================
        // GET UNREAD COUNT (ROLE BASED)
        // =====================================================
        [HttpGet]
        public async Task<IActionResult> GetUnreadCount()
        {
            var userId = GetUserId();
            var role = GetUserRole();

            var query = _context.Notifications.AsQueryable();

            if (role != "Admin")
            {
                query = query.Where(n =>
                    !n.IsRead &&
                    (n.UserId == null || n.UserId.ToString() == userId)
                );
            }
            else
            {
                query = query.Where(n => !n.IsRead);
            }

            var count = await query.CountAsync();

            return Json(count);
        }

        // =====================================================
        // GET LATEST NOTIFICATIONS (ROLE SAFE + FIXED TYPES)
        // =====================================================
        [HttpGet]
        public async Task<IActionResult> GetLatest()
        {
            var userId = GetUserId();
            var role = GetUserRole();

            var query = _context.Notifications
                .Include(n => n.Alert)
                .AsQueryable();

            if (role != "Admin")
            {
                query = query.Where(n =>
                    n.UserId == null ||
                    n.UserId.ToString() == userId
                );
            }

            var data = await query
                .OrderByDescending(n => n.Timestamp)
                .Take(10)
                .Select(n => new
                {
                    id = n.NotificationId,

                    title = n.Alert != null
                        ? n.Alert.Type.ToString()
                        : (n.LogId != null
                            ? "Access Event"
                            : "System Notification"),

                    message = n.Message,

                    severity = n.Alert != null
                        ? n.Alert.Severity.ToString().ToLower()
                        : "info",

                    isRead = n.IsRead,

                    time = n.Timestamp.ToString("hh:mm tt"),

                    type = n.UserId == null ? "system" : "personal"
                })
                .ToListAsync();

            return Json(data);
        }

        // =====================================================
        // MARK ALL AS READ
        // =====================================================
        [HttpPost]
        public async Task<IActionResult> MarkAsRead()
        {
            var userId = GetUserId();
            var role = GetUserRole();

            var query = _context.Notifications.AsQueryable();

            if (role != "Admin")
            {
                query = query.Where(n =>
                    n.UserId == null ||
                    n.UserId.ToString() == userId
                );
            }

            var notifications = await query
                .Where(n => !n.IsRead)
                .ToListAsync();

            foreach (var n in notifications)
            {
                n.IsRead = true;
            }

            await _context.SaveChangesAsync();

            return Ok();
        }

        // =====================================================
        // NOTIFICATION PAGE
        // =====================================================
        public async Task<IActionResult> Index()
        {
            var userId = GetUserId();
            var role = GetUserRole();

            var query = _context.Notifications
                .Include(n => n.Alert)
                .AsQueryable();

            if (role != "Admin")
            {
                query = query.Where(n =>
                    n.UserId == null ||
                    n.UserId.ToString() == userId
                );
            }

            var data = await query
                .OrderByDescending(n => n.Timestamp)
                .ToListAsync();

            return View(data);
        }
    }
}