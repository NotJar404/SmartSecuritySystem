using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class CamerasController : Controller
    {
        private readonly AppDbContext _context;

        public CamerasController(AppDbContext context)
        {
            _context = context;
        }

        // ===============================
        // LOAD INDEX
        // ===============================
        public IActionResult Index()
        {
            LoadRooms();
            return View(GetCameras());
        }

        // ===============================
        // ADD CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(Camera camera)
        {
            LoadRooms();

            LogCamera("ADD CAMERA", camera);

            // 🔥 SHOW EXACT MODEL ERRORS
            if (!ModelState.IsValid)
            {
                LogModelErrors();
                return View("Index", GetCameras());
            }

            // VALIDATE ROOM
            if (!_context.Rooms.Any(r => r.RoomId == camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room selected.");
                return View("Index", GetCameras());
            }

            // CHECK DUPLICATE
            bool duplicate = _context.CameraDevices.Any(c =>
                c.RoomId == camera.RoomId &&
                c.StreamUrl == camera.StreamUrl
            );

            if (duplicate)
            {
                ModelState.AddModelError("", "Camera already exists in this room.");
                return View("Index", GetCameras());
            }

            try
            {
                camera.Status = "active";

                _context.CameraDevices.Add(camera);
                _context.SaveChanges();

                Console.WriteLine("✅ CAMERA SAVED");

                return RedirectToAction(nameof(Index));
            }
            catch (Exception ex)
            {
                LogException(ex);
                ModelState.AddModelError("", ex.InnerException?.Message ?? ex.Message);
                return View("Index", GetCameras());
            }
        }

        // ===============================
        // EDIT CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(Camera camera)
        {
            LoadRooms();

            LogCamera("EDIT CAMERA", camera);

            if (!ModelState.IsValid)
            {
                LogModelErrors();
                return View("Index", GetCameras());
            }

            var existing = _context.CameraDevices
                .FirstOrDefault(c => c.Id == camera.Id);

            if (existing == null)
                return RedirectToAction(nameof(Index));

            // VALIDATE ROOM
            if (!_context.Rooms.Any(r => r.RoomId == camera.RoomId))
            {
                ModelState.AddModelError("", "Invalid room.");
                return View("Index", GetCameras());
            }

            // CHECK DUPLICATE
            bool duplicate = _context.CameraDevices.Any(c =>
                c.Id != camera.Id &&
                c.RoomId == camera.RoomId &&
                c.StreamUrl == camera.StreamUrl
            );

            if (duplicate)
            {
                ModelState.AddModelError("", "Duplicate camera found.");
                return View("Index", GetCameras());
            }

            try
            {
                // UPDATE FIELDS
                existing.Name = camera.Name;
                existing.RoomId = camera.RoomId;
                existing.StreamUrl = camera.StreamUrl;
                existing.Location = camera.Location;
                existing.Status = string.IsNullOrEmpty(camera.Status) ? "active" : camera.Status;

                _context.SaveChanges();

                Console.WriteLine("✅ CAMERA UPDATED");

                return RedirectToAction(nameof(Index));
            }
            catch (Exception ex)
            {
                LogException(ex);
                ModelState.AddModelError("", ex.InnerException?.Message ?? ex.Message);
                return View("Index", GetCameras());
            }
        }

        // ===============================
        // DELETE CAMERA
        // ===============================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            var cam = _context.CameraDevices.FirstOrDefault(c => c.Id == id);

            if (cam != null)
            {
                _context.CameraDevices.Remove(cam);
                _context.SaveChanges();
                Console.WriteLine("🗑 CAMERA DELETED");
            }

            return RedirectToAction(nameof(Index));
        }

        // ===============================
        // HELPERS
        // ===============================
        private List<Camera> GetCameras()
        {
            return _context.CameraDevices
                .Include(c => c.Room)
                .ToList();
        }

        private void LoadRooms()
        {
            ViewBag.Rooms = _context.Rooms.ToList();
        }

        private void LogCamera(string title, Camera cam)
        {
            Console.WriteLine($"=== {title} ===");
            Console.WriteLine($"Id: {cam.Id}");
            Console.WriteLine($"Name: {cam.Name}");
            Console.WriteLine($"RoomId: {cam.RoomId}");
            Console.WriteLine($"StreamUrl: {cam.StreamUrl}");
            Console.WriteLine($"Location: {cam.Location}");
            Console.WriteLine($"Status: {cam.Status}");
        }

        private void LogModelErrors()
        {
            Console.WriteLine("❌ MODELSTATE ERRORS:");

            foreach (var key in ModelState.Keys)
            {
                var state = ModelState[key];

                if (state != null)
                {
                    foreach (var error in state.Errors)
                    {
                        Console.WriteLine($"Field: {key} | Error: {error.ErrorMessage}");
                    }
                }
            }
        }

        private void LogException(Exception ex)
        {
            Console.WriteLine("🔥 EXCEPTION:");
            Console.WriteLine(ex.Message);
            Console.WriteLine(ex.InnerException?.Message);
        }
    }
}